'use strict';
// Device drawer: Interfaces and Logs (docs/parity-campaign/C03-DESIGN.md section 4.1). Two <details> sections
// in index.html, closed until the student opens one, shown only while the VM's helper reports `diagnostics`.
// The browser never names a container or a lab: it sends the manager's lab id and device name. Log text is
// transient (the manager redacts it; nothing here stores it). This file declares only diag*/DIAG_* names and
// loads in Node: browser listeners (visibilitychange, the drawer's close) live in shell.js and call
// diagVisibilityChanged() and resetDeviceDiagnostics() behind typeof guards.
const DIAG_INTERVAL=5000, DIAG_SLOWEST=30000, DIAG_ERRORS=3, DIAG_PAUSE=30*60*1000, DIAG_LOG_MAX=2000, DIAG_NEAR=30;
const DIAG_NO_CONTAINER='No container for this device yet (deploy the lab, or wait for the deploy to create it).';
const DIAG_LOG_EMPTY='The container has written nothing yet.';
const DIAG_PAUSED='Updating paused, retrying…';
const DIAG_MANAGEMENT='the manager reaches the device through it';
// ---- Pure helpers (tested in tests/test_device_diagnostics_ui.js) -------------------------------------------------
function diagPlan(now){return {interval:DIAG_INTERVAL,errors:0,startedAt:now};}
// The one poll plan for both sections: the next request is scheduled only after the previous answer; a 503 doubles the
// wait up to 30 s and a success halves it back; three errors in a row stop it (Retry); 30 minutes pause it (Resume).
function diagPollNext(plan,answer,now){
 const next={interval:plan.interval,errors:plan.errors,startedAt:plan.startedAt};let stop='';
 if(answer&&answer.ok){next.errors=0;next.interval=Math.max(DIAG_INTERVAL,next.interval/2);}
 else if(answer&&answer.status===503){next.interval=Math.min(DIAG_SLOWEST,next.interval*2);}
 else{next.errors+=1;if(next.errors>=DIAG_ERRORS)stop='retry';}
 if(!stop&&now-next.startedAt>=DIAG_PAUSE)stop='resume';
 return {plan:next,delay:stop?null:next.interval,stop};
}
function diagKeyOf(lab,device){return String(lab||'')+'/'+String(device||'');}
function diagSafeName(value){return String(value||'').replace(/[^A-Za-z0-9._-]+/g,'-').replace(/^[-.]+|[-.]+$/g,'')||'x';}
function diagExportName(lab,device,date){return diagSafeName(lab)+'-'+diagSafeName(device)+'-logs-'+date.toISOString().replace(/[-:]/g,'').replace(/\.\d+/,'')+'.txt';}
function diagBytes(value){
 const n=Number(value);if(!Number.isFinite(n)||n<0)return '—';
 if(n<1000)return Math.round(n)+' B';
 const units=['kB','MB','GB','TB'];let size=n/1000,i=0;
 while(size>=1000&&i<units.length-1){size/=1000;i++;}
 return size.toFixed(size<10?2:1)+' '+units[i];
}
function diagRateText(value){
 const n=Number(value);if(!Number.isFinite(n)||n<0)return '';
 if(n<1000)return Math.round(n)+' B/s';
 if(n<1e6)return (n/1000).toFixed(1)+' kB/s';
 return (n/1e6).toFixed(1)+' MB/s';
}
// A rate only from two samples of the same container run (same id and start), the same interface, a non-negative
// delta and a positive time step; anything else is a new baseline and shows bytes alone.
function diagRate(prev,cur,name){
 if(!prev||!cur||!prev.facts||!cur.facts)return null;
 if(!cur.facts.id||prev.facts.id!==cur.facts.id||prev.facts.started!==cur.facts.started)return null;
 const a=prev.counters&&prev.counters[name],b=cur.counters&&cur.counters[name];if(!a||!b)return null;
 const dt=Number(cur.sampled_at)-Number(prev.sampled_at);if(!(dt>0))return null;
 const rx=Number(b.rx_bytes)-Number(a.rx_bytes),tx=Number(b.tx_bytes)-Number(a.tx_bytes);
 if(!(rx>=0)||!(tx>=0))return null;
 return {rx:rx/dt,tx:tx/dt};
}
// Docker's RFC 3339 stamp as a sortable key (fraction padded to nanoseconds); '' for anything else.
function diagStampKey(at){
 const m=/^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d{1,9}))?Z$/.exec(String(at||''));
 return m?m[1]+'.'+(m[2]||'').padEnd(9,'0'):'';
}
// The Follow cursor: the stamp of the last line that has one (a stampless last line never hides it).
function diagCursor(lines){
 for(let i=(lines||[]).length-1;i>=0;i--)if(lines[i]&&lines[i].at)return lines[i].at;
 return '';
}
// An incoming line is dropped only when its own stamp is at or before the cursor; a stampless line is kept.
function diagFreshLines(lines,cursor){
 const limit=diagStampKey(cursor);if(!limit)return (lines||[]).slice();
 return (lines||[]).filter(line=>{const key=line&&line.at?diagStampKey(line.at):'';return !key||key>limit;});
}
function diagTime(at){const m=/T(\d\d:\d\d:\d\d)/.exec(String(at||''));return m?m[1]:'';}
function diagLineText(line){const time=diagTime(line.at);return (time?time+' ':'')+line.text;}
function diagLineFull(line){return (line.at?line.at+' ':'')+line.text;}
function diagFilter(lines,text){
 const needle=String(text||'').trim().toLowerCase();if(!needle)return lines;
 return lines.filter(line=>diagLineText(line).toLowerCase().includes(needle));
}
function diagCount(shown,total,filtered){return (filtered?shown+' of '+total:String(total))+' '+(total===1?'line':'lines');}
// Apply one /logs answer to the log state. replace: Refresh, open, resume (the answer is the content); otherwise the
// Follow append. Returns {fresh, dropped}: the lines to add and the oldest lines pushed out by the 2000-line cap.
function diagApplyLogs(log,incoming,replace){
 const lines=Array.isArray(incoming)?incoming:[];
 if(replace){
  const over=Math.max(0,lines.length-DIAG_LOG_MAX);
  log.lines=lines.slice(over);log.older=over>0;log.missing=false;log.cursor=diagCursor(log.lines);
  return {fresh:log.lines,dropped:[],replaced:true};
 }
 const fresh=diagFreshLines(lines,log.cursor);
 let all=log.lines.concat(fresh),dropped=[];
 if(all.length>DIAG_LOG_MAX){dropped=all.slice(0,all.length-DIAG_LOG_MAX);all=all.slice(all.length-DIAG_LOG_MAX);log.older=true;}
 log.lines=all;
 const cursor=diagCursor(lines);
 if(cursor&&(!log.cursor||diagStampKey(cursor)>=diagStampKey(log.cursor)))log.cursor=cursor;
 log.missing=lines.length>=DIAG_LOG_MAX;
 return {fresh,dropped,replaced:false};
}
// Follow scrolls only when the reader was within 30 px of the bottom before the append.
function diagNearBottom(box){return box.scrollHeight-box.scrollTop-box.clientHeight<=DIAG_NEAR;}
// Data interfaces first, then management, then the internal ones (cEOS cpu/fabric, cJunosEvolved eth1-eth3).
function diagGroups(list){
 const groups={data:[],management:[],internal:[]};
 for(const item of list||[])(groups[item.role]||groups.internal).push(item);
 return groups;
}
function diagEmptySentence(answer){
 if(!answer||answer.present===false)return DIAG_NO_CONTAINER;
 const status=answer.facts&&answer.facts.status;
 if(status==='running')return 'No interfaces reported.';
 return `The container is stopped (${status||'unknown'}). Interfaces exist only while it runs; Logs shows its last output.`;
}
function diagImpairment(row){
 const parts=[];
 for(const key of ['delay','jitter','loss','rate','corruption'])if(row&&row[key]!==undefined&&row[key]!==null&&row[key]!=='')parts.push(key+' '+row[key]);
 return parts.join(' · ');
}
function diagStateClass(state){return state==='up'?'up':state==='down'?'down':'other';}
function diagCounterCell(c,rate,dir){
 if(!c)return '<td>—</td>';
 const bytes=dir==='rx'?c.rx_bytes:c.tx_bytes,packets=dir==='rx'?c.rx_packets:c.tx_packets,errors=dir==='rx'?c.rx_errors:c.tx_errors,dropped=dir==='rx'?c.rx_dropped:c.tx_dropped;
 const title=`${packets} packets, ${errors} errors, ${dropped} dropped`;
 return `<td title="${esc(title)}">${esc(diagBytes(bytes))}${rate?`<small>${esc(diagRateText(rate[dir]))}</small>`:''}</td>`;
}
function diagInterfaceRow(item,ctx){
 const c=ctx.counters&&ctx.counters[item.name],rate=ctx.rates&&ctx.rates[item.name],impair=ctx.impair&&ctx.impair[item.name];
 const meta=[item.mac,item.mtu?'MTU '+item.mtu:'',item.type].filter(Boolean).join(' · ');
 const name=item.role==='management'?`<strong>${esc(item.name)}</strong> · management (${esc(DIAG_MANAGEMENT)})`:`<strong>${esc(item.name)}</strong>`;
 const capture=item.role==='data'?`<button type="button" class="button ghost small" data-diag-capture="${esc(item.name)}" data-diag-key="capture:${esc(item.name)}" aria-label="Capture packets on ${esc(item.name)}" ${ctx.captureAttrs||''}>Capture</button>`:'';
 return `<tr><td>${name}${meta?`<small class="mono">${esc(meta)}</small>`:''}${impair?`<small class="diag-impair">${esc(impair)}</small>`:''}${capture}</td><td>${esc(item.port)||'—'}</td><td><span class="diag-state diag-state-${diagStateClass(item.state)}">${esc(item.state)||'—'}</span></td>${diagCounterCell(c,rate,'rx')}${diagCounterCell(c,rate,'tx')}</tr>`;
}
function diagInterfaceTable(rows,ctx,label,key){
 return `<div class="table-wrap diag-wrap" tabindex="0" role="region" aria-label="${esc(label)}" data-diag-key="${esc(key)}"><table class="diag-table"><caption class="sr-only">${esc(label)}</caption><thead><tr><th scope="col">Name</th><th scope="col">Port</th><th scope="col">State</th><th scope="col">RX</th><th scope="col">TX</th></tr></thead><tbody>${rows.map(r=>diagInterfaceRow(r,ctx)).join('')}</tbody></table></div>`;
}
// ctx: {device, rates, impair, captureAttrs, captureReason, otherOpen}
function diagInterfacesMarkup(answer,ctx){
 if(!answer)return '';
 if(answer.present===false)return `<p class="diag-empty">${esc(DIAG_NO_CONTAINER)}</p>`;
 const list=answer.interfaces||[];
 if(!list.length)return `<p class="diag-empty">${esc(diagEmptySentence(answer))}</p>`;
 const groups=diagGroups(list),main=groups.data.concat(groups.management),withCounters={...ctx,counters:answer.counters};
 let html=main.length?diagInterfaceTable(main,withCounters,'Interfaces of '+ctx.device,'region:main'):'';
 if(groups.internal.length)html+=`<details class="diag-other" data-diag-other ${ctx.otherOpen?'open':''}><summary>Other interfaces (${groups.internal.length})</summary>${diagInterfaceTable(groups.internal,withCounters,'Other interfaces of '+ctx.device,'region:other')}</details>`;
 if(answer.counters_reason)html+='<p class="caption">Traffic counters are not available for this device right now.</p>';
 if(ctx.captureReason)html+=`<p class="caption">${esc(ctx.captureReason)}</p>`;
 return html;
}
function diagLineMarkup(line){return `<span class="diag-line"${line.at?` title="${esc(line.at)}"`:''}>${esc(diagLineText(line))}\n</span>`;}
// ---- State ------------------------------------------------------------------------------------------------------
function diagSectionNew(){return {open:false,timer:0,flight:false,queued:null,plan:diagPlan(0),stopped:'',hidden:false,kind:'',message:'',shown:false,token:0};}
function diagIfNew(){return {sample:null,answer:null,rates:{},impair:{},impairStamp:null,otherOpen:false};}
function diagLogNew(){return {lines:[],cursor:'',tail:200,follow:false,find:'',older:false,missing:false,truncated:false,present:true,loaded:false};}
let diagKey='', diagFacts=null, diagFactsSeen='', diagEpoch=0, diagCapsAsked=0, diagSec={interfaces:diagSectionNew(),logs:diagSectionNew()}, diagIf=diagIfNew(), diagLog=diagLogNew();
const diagIds={interfaces:{box:'diag-interfaces',status:'diag-if-status',retry:'diag-if-retry',loaded:'Interfaces loaded.',pause:'Interface updates paused after 30 minutes.'},logs:{box:'diag-logs',status:'diag-log-status',retry:'diag-log-retry',loaded:'Logs loaded.',pause:'Follow paused after 30 minutes.'}};
function diagWants(name){return diagSec[name].open&&(name==='interfaces'||diagLog.follow);}
function diagSay(name,kind,text){
 const sec=diagSec[name],status=$(diagIds[name].status);sec.kind=kind;
 if(status&&status.textContent!==text)status.textContent=text;
}
function diagRetryButton(name,stopped){
 const sec=diagSec[name],button=$(diagIds[name].retry);sec.stopped=stopped;
 if(button){button.hidden=!stopped;if(stopped)button.textContent=stopped==='resume'?'Resume':'Retry';}
}
// Replace a region's markup only when it changed, and give focus back to the Capture button or scroll region that held it.
function diagSet(el,html){
 if(!el||el._diagHtml===html)return false;
 const active=typeof document!=='undefined'?document.activeElement:null;
 const held=active&&active.dataset&&typeof el.contains==='function'&&el.contains(active)?active.dataset.diagKey:undefined;
 el.innerHTML=html;el._diagHtml=html;
 if(held&&typeof el.querySelector==='function'){const back=el.querySelector('[data-diag-key="'+String(held).replace(/["\\]/g,'\\$&')+'"]');if(back&&!back.disabled&&typeof back.focus==='function')back.focus();}
 return true;
}
function diagOperationStamp(){
 if(typeof state==='undefined'||!state||typeof activeId==='undefined')return '';
 return (state.operations||[]).filter(job=>job.lab_id===activeId&&job.finished).map(job=>String(job.finished)).sort().pop()||'';
}
// ---- Container facts for the drawer (docs/parity-campaign/C04-DESIGN.md section 4.3, pull model) ---------------------
// The Container section of the device panel shows pid, health, start time and published ports only while a diagnostics
// section of this device is open and its poll is running; otherwise null, so the caption "from the Interfaces or Logs
// section while it is open" is never false. Nothing here fetches for it.
function diagnosticsFacts(key){
 if(!diagFacts||!diagFacts.present||key!==diagKey)return null;
 for(const name of ['interfaces','logs']){const sec=diagSec[name];if(sec.open&&!sec.stopped&&diagWants(name))return diagFacts;}
 return null;
}
// Called whenever what diagnosticsFacts would answer may have changed (new facts, a section opened or closed, Follow
// toggled, a poll stopped or restarted): the panel is drawn again only when the answer really differs.
function diagSyncFacts(){
 const now=diagnosticsFacts(diagKey),seen=now?JSON.stringify(now):'';
 if(seen===diagFactsSeen)return;
 diagFactsSeen=seen;
 const dialog=$('details-dialog');
 if(dialog&&dialog.open&&typeof renderDetails==='function')renderDetails();
}
// ---- Interfaces -------------------------------------------------------------------------------------------------
function diagPaintInterfaces(){
 const body=$('diag-if-body');if(!body)return;
 const ctx={device:typeof detailName==='string'?detailName:'',rates:diagIf.rates,impair:diagIf.impair,otherOpen:diagIf.otherOpen,captureAttrs:typeof captureActionAttrs==='function'?captureActionAttrs():'',captureReason:typeof captureStatusLine==='function'?captureStatusLine():''};
 diagSet(body,diagInterfacesMarkup(diagIf.answer,ctx));
}
function diagApplyInterfaces(data,replace){
 const ifs=diagIf;ifs.rates={};
 if(data.present===false){ifs.sample=null;ifs.impair={};}
 else{
  const prev=replace?null:ifs.sample;
  for(const item of data.interfaces||[]){const rate=diagRate(prev,data,item.name);if(rate)ifs.rates[item.name]=rate;}
  ifs.sample=data;
 }
 ifs.answer=data;diagFacts=data.facts&&typeof data.facts==='object'?data.facts:null;diagPaintInterfaces();
}
async function diagFetchInterfaces(){
 const ifs=diagIf,query=new URLSearchParams({lab_id:activeId,node:detailName}).toString();
 const data=await(await api('/operations/interfaces?'+query)).json();
 // Impairments are a line under a row: fetched once per open and after every operation of this lab. A failure leaves the table as it is.
 const stamp=diagOperationStamp();
 if(data.present!==false&&ifs.impairStamp!==stamp){
  try{
   const netem=await(await api('/operations/netem?'+query)).json();
   const map={};for(const row of netem.impairments||[]){const text=diagImpairment(row);if(text&&row.interface)map[row.interface]=text;}
   ifs.impair=map;ifs.impairStamp=stamp;
  }catch(e){if(!e||e.status!==503)ifs.impairStamp=stamp;}
 }
 return data;
}
// ---- Logs -------------------------------------------------------------------------------------------------------
function diagLogNotes(){
 const log=diagLog,notes=[];
 if(!log.loaded)return '';
 if(!log.present)notes.push(DIAG_NO_CONTAINER);
 else if(!log.lines.length)notes.push(DIAG_LOG_EMPTY);
 else if(log.find.trim()&&!diagFilter(log.lines,log.find).length)notes.push('No lines match your search.');
 if(log.older)notes.push('Older lines dropped.');
 if(log.missing)notes.push('Some lines may be missing.');
 if(log.truncated)notes.push('The log is long; only the end of it is shown.');
 return notes.join(' ');
}
function diagPaintLogCount(){
 const count=$('diag-log-count'),log=diagLog;if(!count)return;
 const filtered=!!log.find.trim();
 count.textContent=log.loaded&&log.present?diagCount(diagFilter(log.lines,log.find).length,log.lines.length,filtered):'';
 const note=$('diag-log-note');if(note){const text=diagLogNotes();note.textContent=text;note.hidden=!text;}
}
function diagPaintLogs(){
 const view=$('diag-log-view');if(!view)return;
 view.innerHTML=diagFilter(diagLog.lines,diagLog.find).map(diagLineMarkup).join('');
 diagPaintLogCount();
}
function diagApplyLogsAnswer(data,replace){
 const view=$('diag-log-view'),log=diagLog;
 const near=view?diagNearBottom(view):true;
 log.loaded=true;log.present=data.present!==false;log.truncated=!!data.truncated;
 if(data.facts&&typeof data.facts==='object')diagFacts=data.facts;
 if(!log.present){log.lines=[];log.cursor='';log.older=false;log.missing=false;diagPaintLogs();return;}
 const result=diagApplyLogs(log,data.lines,replace);
 if(result.replaced||!view){diagPaintLogs();if(view)view.scrollTop=view.scrollHeight;return;}
 // A Follow append: drop the pushed-out lines that were on screen, add the new ones, keep the reader where they are.
 for(let n=diagFilter(result.dropped,log.find).length;n>0&&view.firstElementChild;n--)view.firstElementChild.remove();
 const add=diagFilter(result.fresh,log.find);
 if(add.length&&typeof view.insertAdjacentHTML==='function')view.insertAdjacentHTML('beforeend',add.map(diagLineMarkup).join(''));
 diagPaintLogCount();
 if(near&&add.length)view.scrollTop=view.scrollHeight;
}
async function diagFetchLogs(replace){
 const log=diagLog,append=!replace&&log.follow;
 const params={lab_id:activeId,node:detailName,tail:String(append?DIAG_LOG_MAX:log.tail)};
 if(append&&diagStampKey(log.cursor))params.since=log.cursor;
 return (await api('/operations/logs?'+new URLSearchParams(params))).json();
}
function diagShownLines(){return diagFilter(diagLog.lines,diagLog.find);}
function diagExport(){
 const text=diagShownLines().map(diagLineFull).join('\n')+'\n';
 const lab=typeof current==='function'?current():null;
 const link=document.createElement('a'),url=URL.createObjectURL(new Blob([text],{type:'text/plain'}));
 link.href=url;const node=lab&&typeof detailName==='string'?(lab.nodes||[]).find(x=>x.name===detailName):null,device=node?(node.short_name||node.name):typeof detailName==='string'?detailName:'';
 link.download=diagExportName(lab&&lab.name,device,new Date());
 document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
 return link.download;
}
// ---- The poll loop ----------------------------------------------------------------------------------------------
function diagPageVisible(){return typeof pageVisible!=='function'||pageVisible();}
async function diagRun(name,replace){
 const sec=diagSec[name];
 if(!sec.open||sec.stopped)return;
 if(!diagPageVisible()){sec.hidden=true;return;}
 if(sec.flight){sec.queued={replace:!!(sec.queued&&sec.queued.replace)||!!replace};return;}
 clearTimeout(sec.timer);sec.timer=0;sec.flight=true;
 const epoch=diagEpoch,token=sec.token;
 let result;
 try{result={ok:true,data:await(name==='interfaces'?diagFetchInterfaces():diagFetchLogs(replace))};}
 catch(e){result={ok:false,status:e&&e.status?e.status:0,message:e&&e.message?e.message:'The manager did not answer. Try again.'};}
 sec.flight=false;
 if(epoch!==diagEpoch)return;
 if(token===sec.token){
  if(result.ok){
   if(name==='interfaces')diagApplyInterfaces(result.data,!!replace);else diagApplyLogsAnswer(result.data,!!replace);
   sec.shown=true;sec.message='';
   if(sec.kind!=='ok'&&!(name==='logs'&&sec.kind==='follow'&&diagLog.follow))diagSay(name,'ok',diagIds[name].loaded);
  }else sec.message=result.message;
  const polling=diagWants(name),next=diagPollNext(sec.plan,result.ok?{ok:true}:{ok:false,status:result.status},Date.now());
  sec.plan=next.plan;
  // A fetch the person asked for (open, Refresh) that fails has nothing to retry on its own: it stops at once with Retry.
  const stop=next.stop||(!result.ok&&!polling?'retry':'');
  if(stop){
   diagRetryButton(name,stop);
   diagSay(name,'stop',stop==='resume'?diagIds[name].pause:result.ok?'':sec.message);
  }else{
   if(!result.ok)diagSay(name,'err',sec.shown?DIAG_PAUSED:sec.message);
   if(polling){if(diagPageVisible())sec.timer=setTimeout(()=>diagRun(name,false),next.delay);else sec.hidden=true;}
  }
 }
 diagSyncFacts();
 if(sec.queued&&sec.open){const queued=sec.queued;sec.queued=null;diagRun(name,queued.replace);}
 else sec.queued=null;
}
function diagStartSection(name){
 const sec=diagSec[name];
 sec.plan=diagPlan(Date.now());sec.hidden=false;diagRetryButton(name,'');
 diagSay(name,'wait','Loading…');
 return diagRun(name,true);
}
function diagOnToggle(name){
 const box=$(diagIds[name].box),sec=diagSec[name];
 if(!box||box.open===sec.open)return;
 sec.open=box.open;sec.token++;clearTimeout(sec.timer);sec.timer=0;sec.hidden=false;
 if(sec.open){sec.kind='';diagStartSection(name);}
 diagSyncFacts();
}
function diagRetry(name){
 const sec=diagSec[name];
 sec.plan=diagPlan(Date.now());sec.hidden=false;diagRetryButton(name,'');
 diagSay(name,'wait','Loading…');
 diagRun(name,name==='logs'&&!diagLog.follow);
 diagSyncFacts();
}
function diagToggleFollow(){
 const log=diagLog,sec=diagSec.logs,button=$('diag-log-follow');
 log.follow=!log.follow;sec.token++;clearTimeout(sec.timer);sec.timer=0;sec.hidden=false;
 if(button)button.setAttribute('aria-pressed',String(log.follow));
 diagRetryButton('logs','');
 if(log.follow){sec.plan=diagPlan(Date.now());diagSay('logs','follow','Following the log.');diagRun('logs',false);}
 else diagSay('logs','follow','Follow stopped.');
 diagSyncFacts();
}
function diagRefreshLogs(){
 const sec=diagSec.logs;
 sec.plan=diagPlan(Date.now());sec.hidden=false;diagRetryButton('logs','');
 diagRun('logs',true);
 diagSyncFacts();
}
// shell.js calls this on a visibilitychange: a hidden tab stops asking the VM (the timers see it); on return one
// fresh fetch replaces the content and the 30 minutes start again.
function diagVisibilityChanged(){
 if(!diagPageVisible())return;
 for(const name of ['interfaces','logs']){
  const sec=diagSec[name];
  if(!sec.open||sec.stopped||!(sec.hidden||diagWants(name)))continue;
  sec.hidden=false;sec.plan=diagPlan(Date.now());diagRun(name,true);
 }
}
// shell.js calls this when the drawer closes: both sections collapse and every timer, follow and sample is cleared.
function resetDeviceDiagnostics(){
 diagEpoch++;diagKey='';diagFacts=null;diagFactsSeen='';
 for(const sec of Object.values(diagSec))clearTimeout(sec.timer);
 diagSec={interfaces:diagSectionNew(),logs:diagSectionNew()};diagIf=diagIfNew();diagLog=diagLogNew();
 for(const name of ['interfaces','logs']){const box=$(diagIds[name].box),status=$(diagIds[name].status),retry=$(diagIds[name].retry);if(box)box.open=false;if(status)status.textContent='';if(retry)retry.hidden=true;}
 for(const id of ['diag-if-body','diag-log-view']){const el=$(id);if(el){el.innerHTML='';el._diagHtml=undefined;}}
 const follow=$('diag-log-follow');if(follow)follow.setAttribute('aria-pressed','false');
 const find=$('diag-log-find');if(find)find.value='';
 const tail=$('diag-log-tail');if(tail)tail.value='200';
 for(const id of ['diag-log-count','diag-log-note']){const el=$(id);if(el){el.textContent='';if(id==='diag-log-note')el.hidden=true;}}
}
// app.js calls this from renderDetails (every 4 s while the drawer is open): it never rewrites a section's body.
function renderDeviceDiagnostics(n){
 const root=$('details-diagnostics');if(!root)return;
 const enabled=typeof opCaps!=='undefined'&&opCaps&&opCaps.diagnostics===true;
 if(!enabled){
  if(diagKey)resetDeviceDiagnostics();
  root.hidden=true;
  // The first open of the drawer may come before anyone asked the helper what it can do.
  if((typeof opCaps==='undefined'||opCaps===null)&&typeof opCapabilities==='function'&&Date.now()-diagCapsAsked>60000){
   diagCapsAsked=Date.now();
   opCapabilities().then(()=>{const lab=typeof current==='function'?current():null,node=lab&&lab.nodes.find(x=>x.name===detailName);if(node&&$('details-dialog')&&$('details-dialog').open)renderDeviceDiagnostics(node);}).catch(()=>{});
  }
  return;
 }
 root.hidden=false;
 const key=diagKeyOf(typeof activeId==='string'?activeId:'',n&&n.name);
 if(key!==diagKey){resetDeviceDiagnostics();diagKey=key;}
}
// ---- Wiring (element listeners only; document and window listeners are shell.js's) --------------------------------
{
 const on=(id,type,fn,capture)=>{const el=$(id);if(el&&typeof el.addEventListener==='function')el.addEventListener(type,fn,capture);};
 on('diag-interfaces','toggle',()=>diagOnToggle('interfaces'));
 on('diag-logs','toggle',()=>diagOnToggle('logs'));
 on('diag-if-retry','click',()=>diagRetry('interfaces'));
 on('diag-log-retry','click',()=>diagRetry('logs'));
 on('diag-log-refresh','click',diagRefreshLogs);
 on('diag-log-follow','click',diagToggleFollow);
 on('diag-log-export','click',diagExport);
 on('diag-log-tail','change',()=>{const select=$('diag-log-tail');diagLog.tail=Number(select.value)||200;if(diagSec.logs.open)diagRefreshLogs();});
 on('diag-log-find','input',()=>{diagLog.find=$('diag-log-find').value;diagPaintLogs();});
 on('diag-if-body','toggle',event=>{const target=event.target;if(target&&target.hasAttribute&&target.hasAttribute('data-diag-other'))diagIf.otherOpen=!!target.open;},true);
 on('diag-if-body','click',event=>{
  const button=event.target&&event.target.closest?event.target.closest('[data-diag-capture]'):null;
  if(!button||button.disabled||typeof openCapture!=='function')return;
  openCapture(detailName,button.dataset.diagCapture);
 });
}
