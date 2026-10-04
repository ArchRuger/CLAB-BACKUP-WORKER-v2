'use strict';
// The header's save control: the chip, Save, the chip panel and the first save (docs/git-redesign/design/HEADER.md).
// The chip's state, its counts and its names come only from saveChipState in status.js; nothing here decides a state.
// The chip and the panel title are static markup: only className and textContent change on the 4 s poll. The panel body is
// rebuilt through savePanelMarkup only when its markup changed, and focus, the caret and typed text are handed back.
// Every upload ends in gitReviewJob(job,{upload:true}) (git-progress.js), and the first save's Start the repository is the
// only place in the static scripts that asks the manager to start an empty repository.
// Every name of another script is read at call time behind a typeof guard, so this file loads alone in a Node vm context.
// Page memory. refusal: {lab, message, at}, the refusal of a save this page just sent. placing: the lab whose place request runs.
// opened: job id → the status the panel opened by itself for. last: lab id → {key, job}, what the live region last knew.
// naming: the save being named in this panel session. view: {lab, panel, job}, a view shown instead of the chip's own (the result
// of a save that just ended, or the state behind an Also line). places: lab id → {status, data, message}. first: the address
// form. typed: the name typed and not committed. reviewErrors: job id → {key, message}. shown: what the panel body shows now.
// watched: the lab whose Saving… view the open panel showed last (the poll may repaint the panel before the save's end is handed over).
const saveHeader={refusal:null,placing:'',connecting:false,opened:new Map(),last:new Map(),naming:'',view:null,places:new Map(),first:{lab:'',url:'',question:null},typed:null,reviewErrors:new Map(),reviewing:new Set(),uploading:'',sent:'',keeping:'',renaming:'',error:null,shown:{lab:'',view:'',job:''},watched:''};
let saveClock;   // the `now` of the render in progress (tests pass one; the page uses the real time)
const SAVE_EXPOSURE='Saved files can contain passwords or keys.';
const SAVE_URL_ERROR='Paste the HTTPS address, for example https://github.com/you/your-lab-repo.';
const SAVE_BUSY_REPOSITORY='Someone is working in this repository on the VM.';
const SAVE_MISSING='This part of the page did not load. Reload the page and try again.';
function saveEl(id){return typeof $==='function'?$(id):null;}
function saveEsc(value){return typeof esc==='function'?esc(value):String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function saveLab(){return typeof current==='function'?current()||null:null;}
function saveState(){return typeof state==='object'&&state?state:{};}
function saveJobById(id){return id?(saveState().git_jobs||[]).find(job=>job.id===id)||null:null;}
function savePlural(count,word){return typeof plural==='function'?plural(count,word):count+' '+word+(count===1?'':'s');}
function saveHost(lab){return (typeof statusHost==='function'&&statusHost(lab?.git_binding?.repository?.push_url))||'the online repository';}
function saveRepoName(repo){return typeof gitRepoName==='function'?gitRepoName(repo):String(repo?.path||'').split('/').filter(Boolean).pop()||repo?.label||'Repository';}
function saveFolder(value){return String(value||'').replace(/^\/+|\/+$/g,'');}
function saveLongTime(value,now){return typeof relativeTime==='function'?relativeTime(value,now):'';}
// The /api/state document plus what this page remembers, as saveChipState and saveProblem take it: the refusal of a save it just
// sent and, when load.js holds the saved-states list of the lab (loadCtx), its rows, so a loaded lab state is named from that list.
function saveCtx(lab){const base=typeof loadCtx==='function'?loadCtx(lab):saveState();return {...base,refusal:saveHeader.refusal&&lab&&saveHeader.refusal.lab===lab.id?saveHeader.refusal:null};}
// The moment between the click on Save and the manager's answer: git-progress.js holds it in gitSubmitting.
function saveSubmitting(lab){return typeof gitSubmitting!=='undefined'&&!!gitSubmitting&&(typeof gitSubmittingLab==='undefined'||!gitSubmittingLab||gitSubmittingLab===lab.id);}
function saveBusyReason(lab){
 if(typeof busyReason==='function')return String(busyReason(lab.id)||'');
 return typeof busy==='function'&&busy()?'A backup or lab operation is running.':'';
}
// Where a save goes, from its own frozen destination (never from the lab's connection, which may have changed since):
// "<repository> › <folder>", the folder without its saved-state part. '' for a save stored before destinations existed.
function saveDestinationWords(job){
 const d=job&&job.destination;if(!d||!d.repository)return '';
 let folder=saveFolder(d.path);if(folder==='(repository root)')folder='';
 if(job.target!=='move')folder=folder.replace(/(^|\/)(latest|baseline|checkpoints\/[^/]+)$/,'');
 return d.repository+' › '+(folder||'top level');
}
function savePlaceWords(lab){const repo=lab?.git_binding?.repository;return repo?saveRepoName(repo)+' › '+(saveFolder(repo.prefix)||'top level'):'';}
function saveButton(action,label,id,options={}){
 return `<button type="button" class="button ${options.primary?'primary':'ghost small'}" id="${saveEsc(id)}" data-save-action="${saveEsc(action)}"${options.disabled?' disabled':''}${options.describedby?` aria-describedby="${saveEsc(options.describedby)}"`:''}>${saveEsc(label)}</button>`;
}
function saveErrorMarkup(lab){const error=saveHeader.error&&saveHeader.error.lab===lab.id?saveHeader.error.text:'';return `<p class="form-error" role="alert" id="save-panel-error">${saveEsc(error)}</p>`;}
// The sentence under "Saving…", following the job's phase.
function saveSavingSentence(job,lab){
 const keep=' You can keep working.',count=(lab?.git_binding?.node_names||[]).length;
 if(job&&job.target==='update')return 'Updating from the repository.'+keep;
 if(job&&(job.status==='pushing'||(job.status==='queued'&&job.commit&&!job.pushed)))return `Uploading to ${saveHost(lab)}.`+keep;
 if(job&&job.target==='move')return 'Moving the saved files.'+keep;
 if(job&&(job.status==='exporting'||job.captured===false))return 'Saving to the lab VM’s repository.'+keep;
 return (count?`Reading the configuration of ${savePlural(count,'device')}.`:'Reading the device configurations.')+keep;
}
// The summary the sentence is built from: the review's, else the job's stored one. A save of `latest` that changed no file has none
// and reads "Nothing changed since your last save, which is not uploaded yet."
function saveSummaryOf(job,review){
 const summary=(review&&review.summary)||job.summary||null;if(summary)return summary;
 return job.target==='latest'&&job.kind!=='design'&&Array.isArray(job.changed_files)&&!job.changed_files.length?{}:null;
}
function saveSentence(job,review){
 const summary=saveSummaryOf(job,review),also=review?review.also_sends:null;
 return typeof saveChangeSentence==='function'?saveChangeSentence(summary,also,job):'This save is on the lab VM and not uploaded yet.';
}
function saveRowName(row){const name=String(row?.name||'Unnamed save'),lab=row?.lab&&typeof row.lab==='object'?row.lab.name:row?.lab;return row?.job_id?(lab?`${name} (${lab})`:name):`"${name}"`;}
function saveFailedSentence(job,lab,review){
 const host=saveHost(lab),unreachable=/remote branch is unavailable|Git command timed out/i.test(String(job.message||''));
 const rows=review&&Array.isArray(review.also_sends)?review.also_sends:[];
 const first=unreachable?`Your save is safe on the lab VM, but ${host} could not be reached.`:`Your save is safe on the lab VM, but it could not be uploaded to ${host}.`;
 if(!rows.length)return first;
 const names=[saveRowName({job_id:job.id,name:job.note||(job.target==='move'?'Folder move':''),lab:job.lab_name||lab.name}),...rows.map(saveRowName)];
 return `${first} This upload sends ${names.length} saves: ${names.join(', ')}.`;
}
// The review of a waiting save as the views read it: {review, error, pending}. Upload is enabled from `review` alone, in the
// same render that shows its sentence.
function saveReviewOf(job){
 const review=typeof gitReviewCached==='function'?gitReviewCached(job):null;if(review)return {review,error:'',pending:false};
 const key=typeof gitWaitingKey==='function'?gitWaitingKey():'',failed=saveHeader.reviewErrors.get(job.id);
 if(failed&&failed.key===key)return {review:null,error:failed.message||'failed',pending:false};
 return {review:null,error:'',pending:true};
}
function saveAlsoText(also){
 if(!also)return '';
 if(also.key==='waiting')return `Also: ${also.text}.`;
 if(also.key==='failed')return 'Also: the last upload failed.';
 if(also.key==='cant')return 'Also: saving is not possible right now.';
 if(also.key==='running')return `Also: this lab runs ${also.name||String(also.text||'').replace(/^Running /,'')}.`;
 if(also.key==='partial')return `Also: ${also.name||'A saved state'} was loaded on ${also.loaded} of ${savePlural(also.total,'device')}.`;
 return '';
}
// The states the shown view hides, each as one line with Show: the chip's own state when another view is shown, and its `also`s.
function saveAlsoList(cs,panel){
 const load=cs.load||{},withLoad=s=>s&&(s.key==='running'||s.key==='partial')?{...s,name:load.name,loaded:load.loaded,total:load.total}:s;
 const own=cs.panel!==panel&&['cant','failed','waiting','running','partial'].includes(cs.key)?{key:cs.key,text:cs.text,panel:cs.panel,job:cs.job}:null;
 return [own,cs.also,cs.also2].filter(s=>s&&s.panel!==panel).map(withLoad);
}
function saveAlsoMarkup(cs,panel){
 return saveAlsoList(cs,panel).map((also,index)=>{const text=saveAlsoText(also);return text?`<p class="save-note" id="save-also${index?index+1:''}">${saveEsc(text)} ${saveButton('show-also','Show','save-also-show'+(index?index+1:''))}</p>`:'';}).join('');
}
// The lines and the foot that end every view. A lab without a save location has no "Saves to:" line and only Save as a lab state….
function saveTailMarkup(lab,cs,options={}){
 const bound=!!lab.git_binding,ctx=saveCtx(lab),last=options.load===false?null:(typeof loadState==='function'?loadState(lab,ctx,saveClock):null)?.last||null;
 const place=bound&&options.place!==false?`<p class="save-kv" id="save-place"><span>Saves to:</span> ${saveEsc(savePlaceWords(lab))} ${saveButton('place','Change…','save-change',{disabled:!!options.busy})}</p>`:'';
 const when=last?saveLongTime(last.at,saveClock):'';
 const loaded=last&&last.job?`<p class="save-kv" id="save-last-load"><span>Last load:</span> ${saveEsc(last.name+(when?', '+when:''))} ${saveButton('load-details','Details','save-load-details')}</p>`:'';
 const foot=bound?saveButton('versions','All versions','save-all')+saveButton('lab-state','Save as a lab state…','save-as-state')+saveButton('settings','Save settings','save-settings'):saveButton('lab-state','Save as a lab state…','save-as-state');
 return `${place}${loaded}${saveAlsoMarkup(cs,options.panel)}<div class="save-foot">${foot}</div>`;
}
// ---- The views. Each returns {title, dot, name, html, job, needs}; `job` is the id of the job its actions are about. ----
function saveViewSaving(cs,lab){
 return {title:cs.text||'Saving…',dot:'busy',name:'saving',job:cs.job?cs.job.id:'',html:`<p class="save-sub" id="save-saving">${saveEsc(saveSavingSentence(cs.job,lab))}</p>${saveTailMarkup(lab,cs,{busy:true,panel:'saving'})}`};
}
function saveViewUpload(cs,lab,job,failed){
 const {review,error,pending}=saveReviewOf(job),to=saveDestinationWords(job)||savePlaceWords(lab),uploading=saveHeader.uploading===job.id;
 const able=!!review&&!!review.upload_job&&!!review.head,nobody=!!review&&!able;
 const sentence=failed?saveFailedSentence(job,lab,review):saveSentence(job,review);
 const main=error?`<p class="save-sub" id="save-review-failed">What this upload sends could not be read from the lab VM.</p>`:nobody?`<p class="save-sub" id="save-review-busy">${SAVE_BUSY_REPOSITORY}</p>`:'';
 const first=error||nobody?saveButton('review-again','Try again','save-review-again',{primary:true}):saveButton('upload',failed?'Try again':'Upload',failed?'save-retry':'save-upload',{primary:true,disabled:!able||uploading,describedby:'save-checking'});
 const html=`<p class="save-sub" id="save-changes">${saveEsc(sentence)}</p>${to?`<p class="save-kv" id="save-to"><span>To:</span> ${saveEsc(to)}</p>`:''}<p class="save-note" id="save-checking" role="status"${pending?'':' hidden'}>Checking what this upload sends…</p>${main}<div class="save-row">${first}${failed?'':saveButton('not-now','Not now','save-not-now')}${saveButton('changes','See changes','save-see')}${saveButton('details','Details','save-details')}</div>${failed?'':`<p class="save-note">${SAVE_EXPOSURE}</p>`}${saveErrorMarkup(lab)}${saveTailMarkup(lab,cs,{panel:failed?'failed':'upload'})}`;
 return {title:failed?'Upload failed':'Not uploaded yet',dot:failed?'bad':'warn',name:failed?'failed':'upload',job:job.id,html,needs:pending?{review:job}:null};
}
function saveViewCant(cs,lab){
 const problem=typeof saveProblem==='function'?saveProblem(lab,saveCtx(lab)):{sentence:'The save did not work.',actions:[{action:'again',label:'Try again'}],job:null};
 const buttons=(problem.actions||[]).map((item,index)=>saveButton(item.action,item.label,'save-cant-'+item.action,{primary:index===0})).join('');
 return {title:'Can’t save',dot:'bad',name:'cant',job:problem.job?problem.job.id:'',html:`<p class="save-sub" id="save-cant-why">${saveEsc(problem.sentence)}</p><div class="save-row">${buttons}</div>${saveErrorMarkup(lab)}${saveTailMarkup(lab,cs,{panel:'cant'})}`};
}
// Whether the devices are still known to run the lab's latest save: no deploy, redeploy, destroy or design apply finished after it.
function saveRunsLatest(cs,lab){
 if(cs.key!=='saved'||cs.load||typeof statusJobTime!=='function')return false;
 const ctx=saveState(),newest=typeof statusCaptureSaves==='function'?statusCaptureSaves(lab,ctx)[0]:cs.job,at=(typeof statusSaveTime==='function'?statusSaveTime:statusJobTime)(newest||cs.job);if(!at)return false;
 const mine=j=>!!j&&j.lab_id===lab.id,done=j=>!['queued','running'].includes(j.status);
 if((ctx.operations||[]).some(j=>mine(j)&&['deploy','redeploy','destroy'].includes(j.action)&&done(j)&&statusJobTime(j)>at))return false;
 if((ctx.design_jobs||[]).some(j=>mine(j)&&statusJobTime(j)>at))return false;
 if((ctx.restore_jobs||[]).some(j=>mine(j)&&statusJobTime(j)>at&&typeof statusLoadEffective==='function'&&statusLoadEffective(j)))return false;
 return !(typeof statusEpoch==='function'&&statusEpoch(lab.last_deployed)>at);
}
// The checkpoint made from a save's capture, when the manager holds its job.
function saveCheckpointOf(job,lab){return job.backup_job_id?(saveState().git_jobs||[]).find(j=>j.lab_id===lab.id&&j.id!==job.id&&j.target==='checkpoint'&&j.backup_job_id===job.backup_job_id&&!['failed','capture_incomplete','export_pending'].includes(j.status))||null:null;}
function saveNamingMarkup(job,lab){
 const typed=saveHeader.typed&&saveHeader.typed.job===job.id?saveHeader.typed.value:null,value=typed===null?String(job.note||''):typed;
 const checkpoint=saveCheckpointOf(job,lab),keeping=saveHeader.keeping===job.id;
 const why=checkpoint?(checkpoint.checkpoint?`Kept as checkpoint ${checkpoint.checkpoint}.`:'Kept as a checkpoint.'):job.capture_kept===false||!job.backup_job_id?'The capture of this save is no longer kept. Save again to make a checkpoint.':job.capture_whole===false?'This capture does not include the topology. Save again first.':'';
 return `<label class="sr-only" for="save-name">Name of this save</label><input id="save-name" class="save-name" value="${saveEsc(value)}" maxlength="120" autocomplete="off" spellcheck="false"${saveHeader.renaming===job.id?' readonly':''}${typed===null?'':' data-dirty="1"'}>`
  +`<label class="checkbox-label save-keep"><input type="checkbox" id="save-keep" data-save-action="keep"${checkpoint||keeping?' checked':''}${why||keeping?' disabled':''}${why?' aria-describedby="save-keep-why"':''}> Keep as a checkpoint</label>${why?`<p class="save-note" id="save-keep-why">${saveEsc(why)}</p>`:''}${saveErrorMarkup(lab)}`;
}
function saveViewRest(cs,lab,now){
 const job=cs.job,kept=cs.key==='kept',when=saveLongTime(cs.at,now),title=kept?'Kept on this VM':when?'Saved '+when:'Saved';
 // The panel of a finished save always shows its name in the editable field and Keep as a checkpoint (PROMPT 5.3 step 7).
 const naming=!kept&&!!job;
 const head=naming?saveNamingMarkup(job,lab):`<p class="save-sub" id="save-rest-name">${saveEsc((job&&job.note)||'Saved without a name')}</p>`;
 const lines=`${saveRunsLatest(cs,lab)?'<p class="save-kv" id="save-running"><span>Running:</span> your latest save</p>':''}<p class="save-kv" id="save-uploaded"><span>Uploaded:</span> ${kept?'no, kept on the lab VM':saveEsc('yes, to '+saveHost(lab))}</p>`;
 return {title,dot:cs.dot||'ok',name:naming?'naming':'rest',job:job?job.id:'',extra:job?String(job.note||''):'',html:head+lines+(naming?'':saveErrorMarkup(lab))+saveTailMarkup(lab,cs,{panel:'rest'})};
}
function saveFirstTitle(cs,now){if(cs.key==='saved'){const when=saveLongTime(cs.at,now);return when?'Saved '+when:'Saved';}return cs.text||'Not saved yet';}
function saveViewFirst(cs,lab,now){
 const title=saveFirstTitle(cs,now),placing=saveHeader.placing===lab.id,busy=saveBusyReason(lab),held=placing||saveSubmitting(lab);
 const why=!held&&busy?`<p class="save-note" id="save-first-why">${saveEsc(busy+' Save is available when it finishes.')}</p>`:'',blocked=held||!!busy;
 const note=`<p class="save-note">${SAVE_EXPOSURE}</p>`,options={primary:true,disabled:blocked,describedby:why?'save-first-why':''};
 const view=(html,more={})=>({title:placing?(saveHeader.connecting?'Connecting…':'Saving…'):title,dot:placing?'busy':cs.dot||'none',name:'first',job:'',html,...more});
 if(lab.git_binding){
  // Connected, nothing saved yet: the ordinary save, the place stated.
  const repo=lab.git_binding.repository||{},folder=saveFolder(repo.prefix),devices=(lab.git_binding.node_names||[]).length;
  const sentence=`Your first save goes to ${saveRepoName(repo)}, ${folder?'in the folder '+folder:'at its top level'}.`;
  return view(`<p class="save-sub" id="save-first-place">${saveEsc(sentence)}</p><div class="save-row">${devices?saveButton('first-save','Save','save-first',options):''}${saveButton('place','Change…','save-first-place-other',{disabled:held})}</div>${devices?'':'<p class="save-sub" id="save-first-none">This lab has no device whose configuration can be saved.</p>'}${why}${note}${saveErrorMarkup(lab)}${saveTailMarkup(lab,cs,{place:false,panel:'first'})}`);
 }
 const tail=saveTailMarkup(lab,cs,{panel:'first'}),entry=saveHeader.places.get(lab.id);
 if(Array.isArray(lab.nodes)&&!lab.nodes.length)return view(`<p class="save-sub" id="save-first-none">This lab has no device whose configuration can be saved.</p>${tail}`);
 if(!entry||entry.status==='loading')return view(`<p class="save-sub" id="save-first-looking" role="status">Looking for a place to save…</p>${tail}`,{needs:entry?null:{places:true}});
 if(entry.status==='failed')return view(`<p class="save-sub" id="save-cant-why">The lab VM could not be reached.</p><div class="save-row">${saveButton('again','Try again','save-cant-again',{primary:true})}${saveButton('vm','Check the VM connection…','save-cant-vm')}</div><p class="form-error" role="alert" id="save-panel-error">${saveEsc(entry.message||'')}</p>${tail}`);
 const data=entry.data||{},chosen=data.default||null,repositories=Array.isArray(data.repositories)?data.repositories:[];
 if(!chosen||!repositories.length){
  // No repository on the VM: one field for the address. An empty repository asks once before the manager starts it.
  const first=saveHeader.first.lab===lab.id?saveHeader.first:{url:'',question:null},question=first.question,name=question?String(question.name||String(first.url||'').replace(/\/+$/,'').replace(/\.git$/,'').split('/').pop()||'The repository'):'';
  const field=`<label for="save-url">Repository address (HTTPS)</label><input id="save-url" class="save-name" value="${saveEsc(first.url||'')}" placeholder="https://github.com/you/your-lab-repo" autocomplete="off" spellcheck="false" inputmode="url"${question||placing?' readonly':''}>`;
  const lead=placing&&saveHeader.connecting?'<p class="save-sub" id="save-first-wait" role="status">This can take a minute.</p>':'<p class="save-sub">Your saves go to a repository on GitHub. Paste its address; ask your instructor if you do not have one.</p>';
  const row=question?`<p class="save-sub" id="save-first-empty">${saveEsc(name)} is empty. The manager adds a README.md file to start it.</p><div class="save-row">${saveButton('first-start','Start the repository','save-first-start',options)}</div>`
   :`<p class="save-note">The lab VM’s own GitHub login is used. You are never asked for a password or a token here.</p><div class="save-row">${saveButton('first-connect','Save','save-first',options)}</div>`;
  return view(`${lead}${field}${row}${why}<p class="save-note">${SAVE_EXPOSURE} They go into a folder named ${saveEsc(lab.name||'')}.</p>${saveErrorMarkup(lab)}${tail}`);
 }
 const repository=repositories.find(r=>r.id===chosen.repository)||{},repoName=repository.name||saveRepoName(repository),answer=chosen.answer||{},folder=saveFolder(chosen.folder);
 if(chosen.ask){
  // The folder named after the lab holds saves of a lab with the same name: asked once, and the suggested button replaces nobody's saves.
  const beside=saveFolder(chosen.beside);
  return view(`<p class="save-sub" id="save-first-place">This repository already holds saves of a lab named ${saveEsc(lab.name||folder)}.</p><div class="save-row">${beside?saveButton('first-save','Save in '+beside,'save-first',options):''}${saveButton('first-continue','Continue there','save-first-continue',{primary:!beside,disabled:blocked,describedby:options.describedby})}${beside?'':saveButton('place','Choose another place','save-first-place-other',{disabled:held})}</div>${why}${note}${saveErrorMarkup(lab)}${tail}`);
 }
 const sentence=answer.kind==='own-before'?`Your saves continue in ${repoName}, ${folder?'in the folder '+folder:'at its top level'}.`
  :`Your first save goes to ${repoName}, ${!folder?'at its top level':answer.exists===false?'in a folder named '+folder:'in the folder '+folder}.`;
 return view(`<p class="save-sub" id="save-first-place">${saveEsc(sentence)}</p><div class="save-row">${saveButton('first-save','Save','save-first',options)}${saveButton('place','Choose another place','save-first-place-other',{disabled:held})}</div>${why}${note}${saveErrorMarkup(lab)}${tail}`);
}
// Loading, Running and Partial are load.js's view; `shown` is the chip state it is drawn for (the chip's own, or the load behind an Also line).
function saveViewLoad(shown,lab,cs){
 const view=typeof loadChipView==='function'?loadChipView(shown,lab):null,tail=saveTailMarkup(lab,cs,{load:false,panel:shown.panel});
 if(view)return {title:view.title||shown.text,dot:view.dot||shown.dot,name:shown.panel,job:'',extra:String(view.key||''),html:String(view.html||'')+tail};
 return {title:shown.text,dot:shown.dot,name:shown.panel,job:'',html:tail};
}
// The view another state asks for (saveHeader.view), when it still holds: a waiting save, a failed upload, the reason a save
// stopped, the load behind an Also line. Otherwise null and the chip's own view is shown.
function saveWantedView(cs,lab){
 const want=saveHeader.view;if(!want||want.lab!==lab.id)return null;
 if(cs.key==='loading'||cs.key==='saving')return null;
 if(want.panel==='upload'||want.panel==='failed'){
  const job=saveJobById(want.job);if(!job||!job.commit||job.pushed||!['committed','review_pending','push_pending','interrupted'].includes(job.status))return null;
  return {panel:job.status==='push_pending'?'failed':'upload',job};
 }
 const holds=[cs,cs.also,cs.also2].some(s=>s&&s.panel===want.panel);
 return holds&&['cant','running','partial'].includes(want.panel)?{panel:want.panel,job:null}:null;
}
// Pure: the chip panel for a chip state → {title, dot, key, html, name, job, needs}. The views: first, saving, upload, failed, cant,
// rest (and its naming form); loading, running and partial are load.js's (loadChipView). `key` holds no time and no typed text.
function savePanelView(cs,lab,now){
 if(!cs||!lab)return {title:'',dot:'none',key:'',html:'',name:'',job:'',needs:null};
 saveClock=now;
 const wanted=saveWantedView(cs,lab),panel=wanted?wanted.panel:saveSubmitting(lab)&&cs.key!=='loading'?'saving':cs.panel;
 let view;
 if(panel==='saving')view=saveViewSaving(cs.key==='saving'?cs:{...cs,text:'Saving…',job:null},lab);
 else if(panel==='upload'||panel==='failed'){const job=wanted?wanted.job:cs.job;view=job?saveViewUpload(cs,lab,job,panel==='failed'):saveViewCant(cs,lab);}
 else if(panel==='cant')view=saveViewCant(cs,lab);
 else if(panel==='rest')view=saveViewRest(cs,lab,now);
 else if(panel==='loading'||panel==='running'||panel==='partial'){const other=[cs.also,cs.also2].find(s=>s&&s.panel===panel);view=saveViewLoad(cs.panel===panel||!other?cs:{...cs,key:other.key,text:other.text,panel:other.panel,job:other.job,dot:other.key==='running'?'info':'warn',also:null,also2:null},lab,cs);}
 else view=saveViewFirst(cs,lab,now);
 const key=[view.name,view.job||'',view.extra||'',String(view.html).replace(/ value="[^"]*"/g,'')].join('\n');
 return {title:view.title,dot:view.dot,key,html:view.html,name:view.name,job:view.job||'',needs:view.needs||null};
}
// Like setListMarkup (app.js): rebuild only when the key changed, and hand focus, the caret and text the person typed but did not
// commit back to the control with the same id. Every focusable control of a panel body has a stable id. When the focused control
// no longer exists after a rebuild, focus goes to the panel title, never to <body>.
function savePanelMarkup(el,key,build){
 if(!el||el._listKey===key)return false;
 const a=typeof document!=='undefined'&&document?document.activeElement:null,inside=!!a&&!!a.id&&typeof el.contains==='function'&&el.contains(a);
 const typed=inside&&a.dataset&&a.dataset.dirty==='1'?{value:a.value,start:a.selectionStart,end:a.selectionEnd}:null,id=inside?a.id:'';
 el.innerHTML=build();el._listKey=key;
 if(id){
  const next=saveEl(id);
  if(next&&typeof next.focus==='function'&&!next.disabled){
   if(typed&&'value' in next){next.value=typed.value;if(next.dataset)next.dataset.dirty='1';}
   next.focus({preventScroll:true});
   if(typed&&typeof next.setSelectionRange==='function'){try{next.setSelectionRange(typed.start,typed.end);}catch{}}
  }else{const title=saveEl('save-panel-title');if(title&&typeof title.focus==='function')title.focus({preventScroll:true});}
 }
 return true;
}
// The sentence the live region says for a chip state: the panel title and, where there is one, the panel's first sentence.
function saveLiveSentence(cs,lab){
 const title=cs.key==='waiting'?'Not uploaded yet':cs.text,end=/[.…!?]$/.test(title)?'':'.';
 let more='';
 if(cs.key==='waiting'&&cs.job)more=saveSentence(cs.job,null);
 else if(cs.key==='failed'&&cs.job)more=saveFailedSentence(cs.job,lab,null);
 else if(cs.key==='cant'&&typeof saveProblem==='function')more=saveProblem(lab,saveCtx(lab)).sentence;
 else if(cs.key==='saving')more=saveSavingSentence(cs.job,lab);
 return title+end+(more?' '+more:'');
}
function saveSay(text){const live=saveEl('save-live');if(live)live.textContent=text;}
function saveLoadPlaces(id){
 const entry={status:'loading',data:null,message:''};saveHeader.places.set(id,entry);
 (async()=>{
  try{entry.data=await(await api('/labs/'+encodeURIComponent(id)+'/git/places')).json();entry.status='ready';}
  catch(error){entry.status='failed';entry.message=String(error&&error.message||'');}
  if(saveHeader.places.get(id)===entry)renderSaveHeader();
 })();
}
function saveLoadReview(job){
 const key=typeof gitWaitingKey==='function'?gitWaitingKey():'',mark=job.id+'|'+key;
 if(typeof gitReviewData!=='function'||saveHeader.reviewing.has(mark))return;
 saveHeader.reviewing.add(mark);
 gitReviewData(job).then(()=>{saveHeader.reviewErrors.delete(job.id);},error=>{saveHeader.reviewErrors.set(job.id,{key,message:String(error&&error.message||'failed')});})
  .then(()=>{saveHeader.reviewing.delete(mark);renderSaveHeader();if(typeof saveDrawerRender==='function')saveDrawerRender();});
}
// Called by render() on every poll and by this file after each action.
function renderSaveHeader(now){
 const chip=saveEl('save-chip');if(!chip||typeof saveChipState!=='function')return;
 const lab=saveLab();if(!lab)return;
 if(saveHeader.shown.lab!==lab.id){saveHeader.shown={lab:lab.id,view:'',job:''};saveHeader.view=null;saveHeader.naming='';saveHeader.typed=null;saveHeader.error=null;}
 const cs=saveChipState(lab,saveCtx(lab),now),submitting=saveSubmitting(lab)&&cs.key!=='loading'&&cs.key!=='saving';
 const text=submitting?'Saving…':cs.text,dot='save-dot '+(submitting?'busy':cs.dot||'none');
 const write=(id,key,value)=>{const el=saveEl(id);if(el&&el[key]!==value)el[key]=value;};
 write('save-chip-text','textContent',text);write('save-chip-dot','className',dot);
 // Save and Load, each disabled with its reason as visible text: the chip says a load or a save runs; the line under the
 // buttons says anything else. A lab without a save location keeps Save enabled: it opens the first-save view.
 const placing=saveHeader.placing===lab.id,bound=!!lab.git_binding,own=cs.saveDisabled||submitting;
 const busy=!own&&!placing&&bound?saveBusyReason(lab):'',reason=placing?'The place to save is being set.':busy?busy+' Save is available when it finishes.':'';
 write('git-save-progress','textContent','Save');write('git-save-progress','disabled',own||placing||!!busy);
 const line=saveEl('save-reason');if(line){if(line.textContent!==reason)line.textContent=reason;if(line.hidden!==!reason)line.hidden=!reason;}
 write('load-button','disabled',!!cs.loadDisabled);
 // The live region: written when the chip's state changes after the first render of the lab, never on a time tick, and silent
 // for the two endings a toast announces (nothing changed, uploaded).
 const key=submitting?'saving':cs.key,before=saveHeader.last.get(lab.id);
 if(!before||before.key!==key){
  const ended=before&&before.key==='saving'?saveJobById(before.job):null,toast=!!ended&&(ended.status==='unchanged'||ended.status==='synced');
  if(before&&!toast)saveSay(saveLiveSentence(submitting?{...cs,key:'saving',text:'Saving…',job:null}:cs,lab));
 }
 saveHeader.last.set(lab.id,{key,job:cs.key==='saving'&&cs.job?cs.job.id:before&&key==='saving'?before.job:''});
 const view=savePanelView(cs,lab,now);
 write('save-panel-title-text','textContent',view.title);write('save-panel-dot','className','save-dot '+view.dot);
 const panel=saveEl('save-panel'),body=saveEl('save-panel-body');
 if(!panel||panel.hidden||!body)return;
 saveHeader.shown={lab:lab.id,view:view.name,job:view.job};
 if(view.name==='saving')saveHeader.watched=lab.id;
 savePanelMarkup(body,view.key,()=>view.html);
 if(view.needs&&view.needs.places&&typeof api==='function')saveLoadPlaces(lab.id);
 if(view.needs&&view.needs.review)saveLoadReview(view.needs.review);
}
// 'status' opens the chip panel, 'load' the Load panel. options.focus===false leaves focus where it is. Returns whether it opened.
function saveOpenPanel(kind,options={}){
 const button=saveEl(kind==='load'?'load-button':'save-chip');if(!button)return false;
 if(typeof button._menuOpen==='function'){button._menuOpen(options);return true;}
 return typeof openPanel==='function'?!!openPanel(kind==='load'?'load-button':'save-chip',options):false;
}
function saveClosePanel(restore){const chip=saveEl('save-chip');return !!chip&&typeof chip._menuClose==='function'&&chip._menuClose(!!restore);}
function savePanelOpen(){const panel=saveEl('save-panel');return !!panel&&!panel.hidden;}
function saveFocusInside(){const panel=saveEl('save-panel'),a=typeof document!=='undefined'&&document?document.activeElement:null;return !!panel&&!!a&&typeof panel.contains==='function'&&panel.contains(a);}
// A refusal of a save request this page sent (called by gitSubmitSave; error null = the request was accepted). A save of the lab on
// screen becomes the failed attempt the chip shows (Can't save); any other request is left to its caller. Returns whether it took it.
function saveRefused(labId,error,values){
 if(!error){if(saveHeader.refusal&&saveHeader.refusal.lab===labId)saveHeader.refusal=null;return false;}
 const lab=saveLab();if(!lab||lab.id!==labId||!saveEl('save-chip')||(values&&values.target&&values.target!=='latest'))return false;
 saveHeader.refusal={lab:labId,message:String(error.message||'The save did not work.'),at:new Date().toISOString()};saveHeader.view=null;
 renderSaveHeader();
 // The manager may have recorded why (lab.git_status: no device selected, the VM's answer): read it now, not with the next poll.
 if(typeof refresh==='function')Promise.resolve().then(refresh).catch(()=>{});
 return true;
}
// A save of the lab on screen that this page started has ended (called by gitStartWatch). Nothing changed and uploaded are a
// toast; every other ending opens the chip panel by itself on that save's result, unless a dialog, a drawer or another menu is
// open, and never twice for the same result. The chip and the live region change either way.
function saveFinished(job){
 if(!job)return false;
 const lab=saveLab(),mine=!!lab&&lab.id===job.lab_id,status=job.status;
 // The panel shows this save: its own view, or the Saving… view it has shown since the click (a poll that arrived first has
 // already repainted it with the chip's state, which is why the view on screen alone cannot tell).
 const watched=mine&&saveHeader.watched===lab.id;if(mine)saveHeader.watched='';
 const shows=mine&&savePanelOpen()&&(saveHeader.shown.job===job.id||saveHeader.shown.view==='saving'||watched||(saveHeader.view&&saveHeader.view.job===job.id));
 const sent=saveHeader.sent===job.id&&savePanelOpen();   // the upload this page sent, which may be the save of another lab
 if(status==='unchanged'||status==='synced'){
  if(typeof notify==='function')notify(status==='unchanged'?'Nothing changed since your last save.':job.target==='update'?'Repository updated.':`Uploaded to ${(typeof statusHost==='function'&&statusHost(job.destination?.remote))||saveHost(mine?lab:null)}.`);
  if(shows||sent){saveHeader.view=null;saveHeader.sent='';saveClosePanel(saveFocusInside());}
  renderSaveHeader();return false;
 }
 const panel=status==='push_pending'?'failed':(status==='review_pending'||status==='committed')&&job.commit?'upload':['export_pending','capture_incomplete','failed','interrupted'].includes(status)?'cant':'';
 if(!panel||!mine||job.kind==='design'||saveHeader.opened.get(job.id)===status){renderSaveHeader();return false;}
 const chip=saveEl('save-chip'),open=savePanelOpen();
 if(!open&&(typeof panelCanOpen!=='function'||!panelCanOpen(chip))){renderSaveHeader();return false;}
 saveHeader.opened.set(job.id,status);saveHeader.view={lab:lab.id,panel,job:job.id};
 if(!open){
  const a=typeof document!=='undefined'&&document?document.activeElement:null,free=!a||a===document.body||a===chip||a===saveEl('git-save-progress');
  saveOpenPanel('status',{focus:free});
 }
 renderSaveHeader();return true;
}
function saveShowError(origin,message){
 const holder=origin&&typeof origin==='object'&&typeof origin.querySelector==='function'?origin.querySelector('.form-error'):origin==='drawer'&&saveEl('save-drawer')&&typeof saveEl('save-drawer').querySelector==='function'?saveEl('save-drawer').querySelector('.form-error'):null;
 if(holder){holder.textContent=message;return;}
 const lab=saveLab();saveHeader.error=lab?{lab:lab.id,text:message}:null;renderSaveHeader();
}
// A drawer of save-drawers.js; the panel closes first and the chip is the control focus returns to.
function saveOpenDrawer(kind,options={}){
 const chip=saveEl('save-chip');saveClosePanel(false);
 if(typeof saveDrawerOpen==='function'){saveDrawerOpen(kind,{opener:chip,...options});return;}
 // A page without the drawers keeps today's places for what it can.
 if((kind==='settings'||kind==='chooser')&&typeof gitOpenRepository==='function'){gitOpenRepository();return;}
 if(kind==='versions'&&typeof gitRunAction==='function'){gitRunAction('load');return;}
 throw new Error(SAVE_MISSING);
}
// An ordinary save of the lab: an empty note (the manager names it), stopped before any upload.
async function saveStart(id){
 if(typeof gitSubmitSave!=='function')throw new Error(SAVE_MISSING);
 try{return await gitSubmitSave(id,{target:'latest',push:true,note:'',allow_removed:true},undefined,{quiet:true});}
 catch(error){if(error&&error.saveShown)return null;throw error;}
}
// The first save: place the lab, then save, in one click. kind: 'save' (the default place, or the folder beside a lab of the same
// name), 'continue' (the folder named after the lab, taken on purpose), 'connect' (the address of a repository the VM does not have
// yet), 'start' (the same after the person agreed to start an empty repository).
// The one place a page script writes the flag that lets the VM helper start an empty repository (a README.md is
// pushed): reached only from a Start the repository button, here and in the folder chooser.
function saveStartBody(body){return {...body,initialize:true};}
async function saveFirstPlace(kind){
 const lab=saveLab();if(!lab||saveHeader.placing)return null;
 const id=lab.id,entry=saveHeader.places.get(id),chosen=entry&&entry.data?entry.data.default:null,base={choice:'',pending:'',move_files:false,acknowledge:true};
 let body;
 if(kind==='connect'||kind==='start'){
  const field=saveEl('save-url'),url=String(kind==='start'?saveHeader.first.url:(field?field.value:saveHeader.first.url)||'').trim();
  if(!/^https:\/\/[^\s/]+\/\S+/.test(url))throw new Error(SAVE_URL_ERROR);
  saveHeader.first={lab:id,url,question:kind==='start'?saveHeader.first.question:null};
  body={url,folder:String(lab.name||'').replace(/\//g,'-'),...base};
  if(kind==='start')body=saveStartBody(body);
 }else{
  if(!chosen)throw new Error('Looking for a place to save…');
  body=kind==='continue'?{repository:chosen.repository,folder:chosen.folder||'',...base,choice:'take'}:{repository:chosen.repository,folder:(chosen.ask?chosen.beside:chosen.folder)||'',...base};
 }
 saveHeader.placing=id;saveHeader.connecting=!!body.url;saveHeader.error=null;renderSaveHeader();
 try{
  const answer=await json('/labs/'+encodeURIComponent(id)+'/git/place','POST',body);
  if(answer&&answer.question){
   if(answer.question.kind==='empty'&&body.url&&!body.initialize){saveHeader.first={lab:id,url:body.url,question:answer.question};return answer;}
   // The repository changed between the two requests: the chooser takes over with the question in it.
   saveHeader.placing='';
   saveOpenDrawer('chooser',{mode:'location',repository:body.repository||'',folder:body.folder,path:body.folder,question:answer.question,then:()=>saveStart(id)});
   return answer;
  }
  saveHeader.first={lab:'',url:'',question:null};saveHeader.places.delete(id);
  if(typeof gitContexts!=='undefined'&&typeof gitContexts.delete==='function')gitContexts.delete(id);
  if(typeof refresh==='function')await refresh();
 }catch(error){
  // A repository that could not be connected explains itself in the manager's own words under the field; any other
  // failure is the failed attempt the chip shows.
  if(body.url)throw error;
  saveHeader.refusal={lab:id,message:String(error&&error.message||'The save did not work.'),at:new Date().toISOString()};return null;
 }finally{saveHeader.placing='';saveHeader.connecting=false;renderSaveHeader();}
 return saveStart(id);
}
// The name of a save (DESIGN.md 3.2): committed on change or Enter, never per keystroke. An empty name returns to the automatic one.
async function saveRename(job,value){
 if(!job||saveHeader.renaming)return null;
 const note=String(value??'').replace(/[\r\n\t]+/g,' ').replace(/\s+/g,' ').trim();
 if(note.length>120){saveShowError(null,'Keep the name to 120 characters or fewer.');return null;}
 if(note===String(job.note||'')){if(saveHeader.typed&&saveHeader.typed.job===job.id)saveHeader.typed=null;return job;}
 const lab=saveLab(),field=saveEl('save-name');
 saveHeader.naming=job.id;saveHeader.renaming=job.id;saveHeader.typed={job:job.id,value:String(value??'')};saveHeader.error=null;if(field)field.readOnly=true;
 try{
  const next=await json('/git/jobs/'+encodeURIComponent(job.id)+'/name','POST',{note});
  if(typeof gitRememberJob==='function')gitRememberJob(next);
  saveHeader.typed=null;const now=saveEl('save-name');if(now){now.value=String(next.note||'');if(now.dataset)now.dataset.dirty='';}
  saveSay('Renamed.');return next;
 }catch(error){saveHeader.error=lab?{lab:lab.id,text:String(error&&error.message||'The name could not be changed.')}:null;return null;}
 finally{saveHeader.renaming='';const now=saveEl('save-name');if(now)now.readOnly=false;renderSaveHeader();}
}
// The one dispatcher of every data-save-action, in the chip panel and in the drawer head. `job` is the save the view is about
// (null where the view has none); `origin` is 'panel', 'drawer' or the element whose .form-error takes a failure.
async function saveAction(action,job,origin){
 const lab=saveLab(),chip=saveEl('save-chip'),drawer=origin==='drawer'||(origin&&typeof origin==='object'&&origin.id==='save-drawer');
 try{
  if(saveHeader.error){saveHeader.error=null;}
  switch(action){
   case 'upload':{
    if(!job||typeof gitReviewJob!=='function')throw new Error(SAVE_MISSING);
    saveHeader.uploading=job.id;renderSaveHeader();
    try{const next=await gitReviewJob(job,{upload:true});saveHeader.sent=next&&next.id||'';}finally{saveHeader.uploading='';}
    if(drawer&&typeof saveDrawerClose==='function')saveDrawerClose();
    break;
   }
   case 'not-now':if(drawer){if(typeof saveDrawerClose==='function')saveDrawerClose();}else saveClosePanel(true);return;
   case 'changes':if(!job||typeof gitReviewJob!=='function')throw new Error(SAVE_MISSING);saveClosePanel(false);await gitReviewJob(job,{opener:chip});return;
   case 'details':
    if(job&&typeof gitShowJob==='function'){saveClosePanel(true);await gitShowJob(job.id,job);return;}
    saveOpenDrawer('settings',{section:'details'});return;
   case 'review-again':{
    if(!job||typeof gitReviewData!=='function')throw new Error(SAVE_MISSING);
    const key=typeof gitWaitingKey==='function'?gitWaitingKey():'',mark=job.id+'|'+key;
    saveHeader.reviewErrors.delete(job.id);saveHeader.reviewing.add(mark);renderSaveHeader();
    try{await gitReviewData(job,{fresh:true});}catch(error){saveHeader.reviewErrors.set(job.id,{key,message:String(error&&error.message||'failed')});}finally{saveHeader.reviewing.delete(mark);}
    break;
   }
   case 'again':{
    if(!lab)return;
    saveHeader.refusal=null;saveHeader.view=null;
    if(job&&(job.kind||['export_pending','interrupted'].includes(job.status)||job.target==='move')){
     // A stopped save that can be retried reuses its capture; a lab state or a design export retries that job, never a save of the lab.
     const next=await json('/git/jobs/'+encodeURIComponent(job.id)+'/retry','POST',{push:false});
     if(typeof gitRememberJob==='function')gitRememberJob(next);if(typeof gitStartWatch==='function')gitStartWatch(next,{quiet:true});if(typeof refresh==='function')await refresh();break;
    }
    if(!lab.git_binding){saveHeader.places.delete(lab.id);break;}
    if(job){await saveStart(lab.id);break;}
    // The repository was not ready, or the request was refused: read the status again; the save follows when it is ready.
    const context=typeof gitLoadContext==='function'?await gitLoadContext(lab.id,true):null,status=(context&&context.repository_status)||{};
    if(typeof refresh==='function')await refresh();
    if(!status.problem&&status.ready!==false)await saveStart(lab.id);
    break;
   }
   case 'vm':saveClosePanel(true);if(typeof openVmDialog==='function')openVmDialog();return;
   case 'update':if(!lab||typeof gitUpdateRemote!=='function')throw new Error(SAVE_MISSING);saveClosePanel(true);await gitUpdateRemote(lab.id);return;
   case 'settings':saveOpenDrawer('settings');return;
   case 'versions':saveOpenDrawer('versions');return;
   case 'lab-state':{const places=lab?saveHeader.places.get(lab.id):null,chosen=places&&places.data?places.data.default:null;saveOpenDrawer('state',chosen&&!lab.git_binding?{repository:chosen.repository}:{});return;}
   case 'place':{
    if(lab&&!lab.git_binding){const places=saveHeader.places.get(lab.id),chosen=places&&places.data?places.data.default:null,id=lab.id;saveOpenDrawer('chooser',{mode:'location',repository:chosen?chosen.repository:'',folder:chosen?chosen.folder:'',path:chosen?chosen.folder:'',then:()=>saveStart(id)});return;}
    saveOpenDrawer('chooser',{mode:'location'});return;
   }
   case 'load-details':{
    const last=lab&&typeof loadState==='function'?loadState(lab,saveCtx(lab)).last:null;
    if(!last||!last.job||typeof restoreShowJob!=='function')throw new Error(SAVE_MISSING);
    saveClosePanel(true);await restoreShowJob(last.job.id);return;
   }
   case 'first-save':if(lab&&lab.git_binding){await saveStart(lab.id);break;}await saveFirstPlace('save');break;
   case 'first-continue':await saveFirstPlace('continue');break;
   case 'first-connect':await saveFirstPlace('connect');break;
   case 'first-start':await saveFirstPlace('start');break;
   case 'keep':{
    if(!lab||!job||typeof gitSubmitSave!=='function')throw new Error(SAVE_MISSING);
    saveHeader.keeping=job.id;saveHeader.naming=job.id;renderSaveHeader();
    try{await gitSubmitSave(lab.id,{target:'checkpoint',checkpoint:'',backup_job_id:job.backup_job_id||'',push:true,note:job.note||'',allow_removed:true},undefined,{quiet:true});}
    finally{saveHeader.keeping='';}
    break;
   }
   case 'show-also':{
    const cs=lab&&typeof saveChipState==='function'?saveChipState(lab,saveCtx(lab)):null,list=cs?saveAlsoList(cs,saveHeader.shown.view==='naming'?'rest':saveHeader.shown.view):[];
    const also=list[Number(origin&&origin.index)||0];if(also)saveHeader.view={lab:lab.id,panel:also.panel,job:also.job?also.job.id:''};
    break;
   }
   default:return;
  }
 }catch(error){saveShowError(origin,String(error&&error.message||'That did not work. Try again.'));return;}
 renderSaveHeader();
}
// One click and one change listener on the panel serve every rebuilt control; nothing is attached to a rebuilt node.
function savePanelJob(){return saveJobById(saveHeader.shown.job);}
function savePanelClick(event){
 const target=event&&event.target&&typeof event.target.closest==='function'?event.target.closest('button[data-save-action]'):null;if(!target||target.disabled)return;
 const action=target.dataset.saveAction,index=action==='show-also'?Number(String(target.id||'').replace('save-also-show',''))||1:1;
 saveAction(action,savePanelJob(),action==='show-also'?{index:index-1}:'panel');
}
function savePanelChange(event){
 const target=event&&event.target;if(!target)return;
 if(target.id==='save-name'){saveRename(savePanelJob(),target.value);return;}
 if(target.id==='save-keep'&&target.checked)saveAction('keep',savePanelJob(),'panel');
}
function savePanelInput(event){
 const target=event&&event.target;if(!target)return;
 if(target.dataset)target.dataset.dirty='1';
 const lab=saveLab();
 if(target.id==='save-url'&&lab)saveHeader.first={lab:lab.id,url:target.value,question:null};
 if(target.id==='save-name'&&saveHeader.shown.job)saveHeader.typed={job:saveHeader.shown.job,value:target.value};
}
// Enter in the name commits and keeps the panel open; Enter in the address field is its Save button.
function savePanelKey(event){
 const target=event&&event.target;if(!target||event.key!=='Enter')return;
 if(target.id==='save-name'){event.preventDefault();saveRename(savePanelJob(),target.value);}
 else if(target.id==='save-url'){event.preventDefault();saveAction('first-connect',null,'panel');}
}
// What a closing panel forgets: the refusal, the name being typed, a view shown in place of the chip's own, the place it looked up.
function savePanelClosed(){
 saveHeader.refusal=null;saveHeader.naming='';saveHeader.typed=null;saveHeader.view=null;saveHeader.error=null;saveHeader.watched='';
 for(const [id,entry] of saveHeader.places)if(entry.status!=='loading'&&saveHeader.placing!==id)saveHeader.places.delete(id);
 const body=saveEl('save-panel-body');if(body)body._listKey=undefined;
 renderSaveHeader();
}
if(typeof $==='function'&&$('save-chip')&&$('save-panel')&&typeof $('save-panel').addEventListener==='function'){
 const panel=$('save-panel');
 panel.addEventListener('click',savePanelClick);panel.addEventListener('change',savePanelChange);panel.addEventListener('input',savePanelInput);panel.addEventListener('keydown',savePanelKey);
 panel.addEventListener('panelopen',()=>renderSaveHeader());panel.addEventListener('panelclose',savePanelClosed);
}
