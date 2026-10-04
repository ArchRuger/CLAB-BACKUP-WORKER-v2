// The header's chip, its panel, the save and upload flow and the first save (docs/git-redesign/design/HEADER.md).
// status.js, diff-view.js, git-progress.js and save-header.js run together in one vm context with a small fake of the header's
// elements; the routes are answered from a fake `json` / `api` exactly as DESIGN.md section 4 defines them.
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const staticDir=path.join(__dirname,'../app/static'),read=name=>fs.readFileSync(path.join(staticDir,name),'utf8');
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const NOW=Date.parse('2026-10-04T12:00:00Z'),ago=minutes=>new Date(NOW-minutes*60000).toISOString();
const CHECKOUT='/home/me/CLAB-MNGR-DEV-LLM';
const binding={binding_id:'b',node_names:['ceos','cjunos','vjunos','xrv9k'],repository:{path:CHECKOUT,prefix:'bgp',push_url:'https://github.com/me/CLAB-MNGR-DEV-LLM.git'}};
const boundLab=(more={})=>({id:'lab',name:'bgp',nodes:[{name:'clab-bgp-ceos',short_name:'ceos'}],git_binding:binding,git_status:{checked:true,ready:true},...more});
const freeLab=(more={})=>({id:'lab',name:'restore-square',nodes:[{name:'n1'}],...more});
const destination={repository:'CLAB-MNGR-DEV-LLM',branch:'main',path:'bgp/latest',checkout:CHECKOUT};
const waiting=(more={})=>({id:'w',lab_id:'lab',lab_name:'bgp',status:'review_pending',target:'latest',captured:true,commit:'c1',created:ago(2),finished:ago(1),note:'ceos and xrv9k changed',note_auto:true,backup_job_id:'bk',summary:{devices:['ceos','xrv9k'],added:19,removed:1},destination,...more});
const saved=(more={})=>waiting({id:'s',status:'synced',pushed:true,commit:'c0',created:ago(22),finished:ago(21),capture_kept:true,capture_whole:true,...more});
const review=(more={})=>({files:[],head:'head-1',upload_job:'w',also_sends:[],...more});
function harness(options={}){
 const statics=new Map(),children=new Map(),calls=[],toasts=[],drawers=[],dialogs=[];
 const make=(id,more={})=>({id,tag:'div',hidden:false,disabled:false,textContent:'',className:'',value:'',dataset:{},listeners:{},focused:0,
  addEventListener(name,fn){this.listeners[name]=fn;},focus(){this.focused++;document.activeElement=this;},contains(other){return !!other&&(other===this||children.get(other.id)===other&&this.id==='save-panel-body'||(this.id==='save-panel'&&(children.get(other.id)===other||['save-panel-title','save-panel-body'].includes(other.id))));},
  querySelector(){return null;},setSelectionRange(start,end){this.selection=[start,end];},...more});
 const document={activeElement:null,body:make('body'),querySelector:()=>null,querySelectorAll:()=>[]};
 const attr=(text,name)=>{const m=text.match(new RegExp(' '+name+'="([^"]*)"'));return m?m[1].replace(/&quot;/g,'"').replace(/&lt;/g,'<').replace(/&gt;/g,'>').replace(/&#39;/g,"'").replace(/&amp;/g,'&'):null;};
 // The panel body: setting innerHTML replaces its controls, as a browser does (the old nodes are gone, focus falls to nothing).
 const body=make('save-panel-body',{_html:'',writes:0});
 Object.defineProperty(body,'innerHTML',{configurable:true,get(){return this._html;},set(html){
  this._html=html;this.writes++;if(document.activeElement&&children.get(document.activeElement.id)===document.activeElement)document.activeElement=document.body;children.clear();
  for(const m of html.matchAll(/<(button|input|p|label|div)\b([^>]*)>/g)){const id=attr(m[2],'id');if(!id)continue;
   children.set(id,make(id,{tag:m[1],disabled:/ disabled\b/.test(m[2]),readOnly:/ readonly\b/.test(m[2]),hidden:/ hidden\b/.test(m[2]),checked:/ checked\b/.test(m[2]),type:attr(m[2],'type')||'',value:attr(m[2],'value')||'',dataset:{...(attr(m[2],'data-save-action')?{saveAction:attr(m[2],'data-save-action')}:{}),...(attr(m[2],'data-dirty')?{dirty:attr(m[2],'data-dirty')}:{})}}));}
 }});
 statics.set('save-panel-body',body);
 for(const id of ['save-chip-dot','save-chip-text','save-panel-title','save-panel-dot','save-panel-title-text','git-save-progress','load-button','save-reason','save-live'])statics.set(id,make(id));
 const panel=make('save-panel',{hidden:true}),chip=make('save-chip');statics.set('save-panel',panel);statics.set('save-chip',chip);
 chip._menuOpen=(opts={})=>{const was=panel.hidden;panel.hidden=false;if(was&&panel.listeners.panelopen)panel.listeners.panelopen();if(opts.focus===true||(was&&opts.focus!==false))statics.get('save-panel-title').focus();return true;};
 chip._menuClose=restore=>{if(panel.hidden)return false;panel.hidden=true;if(panel.listeners.panelclose)panel.listeners.panelclose();if(restore)chip.focus();return true;};
 statics.get('save-reason').hidden=true;
 const state={labs:[options.lab||boundLab()],jobs:[],git_jobs:[],restore_jobs:[],operations:[],design_jobs:[],...(options.state||{})};
 const routes=options.routes||{};
 const answer=async(method,endpoint,payload)=>{
  calls.push({method,endpoint,payload});
  for(const [pattern,reply] of Object.entries(routes))if(endpoint.includes(pattern)){const value=typeof reply==='function'?await reply(payload,endpoint):reply;if(value instanceof Error)throw value;return value;}
  throw Object.assign(new Error('No route for '+endpoint),{status:404});
 };
 const context=vm.createContext({$:id=>statics.get(id)||children.get(id)||null,esc,state,activeId:'lab',document,console,
  utcDisplay:value=>String(value),crypto:{getRandomValues:bytes=>bytes.fill(7)},sessionStorage:{getItem:()=>null,setItem(){},removeItem(){}},setTimeout:()=>0,clearTimeout(){},
  notify:message=>toasts.push(message),opTask:async(dialog,fn)=>fn(),opDialog:(id,title,html)=>{dialogs.push({id,title,html});return {id,open:true,close(){},querySelector:()=>null,querySelectorAll:()=>[]};},
  json:(endpoint,method,payload)=>answer(method,endpoint,payload),api:async endpoint=>({json:()=>answer('GET',endpoint)}),
  panelCanOpen:()=>options.canOpen?options.canOpen():true,busyReason:()=>context.busyText||'',closeMenus(){},
  saveDrawerOpen:(kind,opts)=>drawers.push({kind,opts}),saveDrawerRender(){},saveDrawerClose:()=>drawers.push({kind:'closed'})});
 context.busyText='';context.current=()=>context.state.labs.find(lab=>lab.id===context.activeId);
 context.refresh=async()=>{context.renderSaveHeader(NOW);};
 for(const name of ['status.js','diff-view.js','git-progress.js','save-header.js'])vm.runInContext(read(name),context);
 if(options.without)for(const name of options.without)context[name]=undefined;
 const flush=async()=>{for(let i=0;i<8;i++)await new Promise(resolve=>setImmediate(resolve));};
 const h={context,state,calls,toasts,drawers,dialogs,document,panel,chip,body,flush,el:id=>context.$(id),
  render:()=>context.renderSaveHeader(NOW),
  async open(){chip._menuOpen();context.renderSaveHeader(NOW);await flush();context.renderSaveHeader(NOW);},
  // A click as the delegated listener serves it: the control must exist, be a button with an action and be enabled.
  async press(id){const el=children.get(id);assert.ok(el,'control #'+id+' is in the panel');assert.equal(el.tag,'button');assert.ok(el.dataset.saveAction,'#'+id+' has an action');assert.equal(el.disabled,false,'#'+id+' is enabled');
   panel.listeners.click({target:{...el,closest:()=>el}});await flush();context.renderSaveHeader(NOW);},
  posts:()=>calls.filter(c=>c.method==='POST'),text:id=>statics.get(id).textContent,
  mem:()=>vm.runInContext('saveHeader',context),view(){const lab=context.current();return context.savePanelView(context.saveChipState(lab,{...context.state,refusal:this.mem().refusal},NOW),lab,NOW);}};
 return h;
}
const SAVE_CLASSES=new Set(['save-control','save-pair','save-chip','save-dot','save-panel','save-state','save-sub','save-row','save-note','save-kv','save-foot','save-name','save-keep','save-heading','save-list','save-item','save-when','save-why','save-devices','save-end','save-drawer','save-settings','save-settings-foot']);
function checkMarkup(html,label){
 for(const m of html.matchAll(/class="([^"]*)"/g))for(const token of m[1].split(/\s+/))if(token.startsWith('save-'))assert.ok(SAVE_CLASSES.has(token),label+': class '+token+' is in the list of HEADER.md 1.3');
 assert.doesNotMatch(html,/ style=/,label+': no inline style');
 for(const m of html.matchAll(/<(p|div|span)\b[^>]*(role="(?:status|alert)"|aria-live=)[^>]*>(.*?)<\/\1>/gs))assert.doesNotMatch(m[3],/<button|<input|<a /,label+': a live region holds only its sentence');
 for(const m of html.matchAll(/<(button|input)\b([^>]*)>/g))assert.match(m[2],/ id="[\w-]+"/,label+': every control has an id');
 for(const m of html.matchAll(/<input\b[^>]*type="checkbox"[^>]*>/g))assert.ok(new RegExp('<label[^>]*>'+m[0].replace(/[.*+?^${}()|[\]\\]/g,'\\$&')).test(html),label+': a tick box is a real input inside its label');
}

test('the chip changes textContent and className only, the title carries the long time, and the live region speaks on a change of state alone',async()=>{
 const h=harness({state:{git_jobs:[saved()]}});
 const chipText=h.el('save-chip-text'),dot=h.el('save-chip-dot');
 h.render();
 assert.equal(chipText.textContent,'Saved 21 min ago');assert.equal(dot.className,'save-dot ok');assert.equal(h.text('save-panel-title-text'),'Saved 21 minutes ago');assert.equal(h.el('save-panel-dot').className,'save-dot ok');
 assert.equal(h.el('git-save-progress').textContent,'Save');assert.equal(h.el('git-save-progress').disabled,false);assert.equal(h.el('load-button').disabled,false);
 assert.equal(h.text('save-live'),'','nothing is announced on the first render of a lab');
 h.render();assert.equal(h.el('save-chip-text'),chipText,'the same nodes after a second render');assert.equal(h.body.writes,0,'a closed panel renders no body');
 h.context.renderSaveHeader(NOW+5*60000);assert.equal(chipText.textContent,'Saved 26 min ago');assert.equal(h.text('save-live'),'','a time tick is not announced');
 h.state.git_jobs=[waiting(),saved()];h.render();
 assert.equal(chipText.textContent,'1 save to upload');assert.equal(dot.className,'save-dot warn');
 assert.equal(h.text('save-live'),'Not uploaded yet. 2 devices changed since your last save: ceos and xrv9k. 19 lines added, 1 removed.');
 // Uploaded and nothing changed are the toast's: the region stays as it was.
 h.state.git_jobs=[waiting({status:'pushing'}),saved()];h.render();assert.match(h.text('save-live'),/^Uploading… Uploading to github\.com\./);
 const before=h.text('save-live');h.state.git_jobs=[waiting({status:'synced',pushed:true}),saved()];h.render();assert.equal(h.text('save-live'),before);
 h.state.git_jobs=[waiting({id:'n',status:'capturing',commit:''}),saved()];h.render();h.state.git_jobs=[waiting({id:'n',status:'unchanged',pushed:true}),saved()];const said=h.text('save-live');h.render();assert.equal(h.text('save-live'),said);
});
test('Save and Load are disabled with a visible reason: the chip for a save or a load, the line under the buttons for anything else',()=>{
 const h=harness({state:{git_jobs:[saved()]}}),save=h.el('git-save-progress'),load=h.el('load-button'),reason=h.el('save-reason');
 h.render();assert.equal(save.disabled,false);assert.equal(reason.hidden,true);
 h.context.busyText='A backup is running.';h.render();
 assert.equal(save.disabled,true);assert.equal(reason.hidden,false);assert.equal(reason.textContent,'A backup is running. Save is available when it finishes.');assert.equal(load.disabled,false);
 for(const text of ['Starting lab is running.','A load is running on ospf.','A network design is being applied on ospf.']){h.context.busyText=text;h.render();assert.equal(reason.textContent,text+' Save is available when it finishes.');assert.equal(save.disabled,true);}
 // A save of this lab: the chip says it, the line stays hidden, Load stays enabled.
 h.state.git_jobs=[waiting({status:'capturing',commit:''}),saved()];h.context.busyText='A save is running on bgp.';h.render();
 assert.equal(h.text('save-chip-text'),'Saving…');assert.equal(save.disabled,true);assert.equal(reason.hidden,true);assert.equal(load.disabled,false,'the states can be browsed during a save');
 // A load of this lab: both disabled, the chip says why.
 h.state.git_jobs=[saved()];h.state.restore_jobs=[{id:'r',lab_id:'lab',status:'applying',created:ago(1),targets:[{node:'a',status:'verified'},{node:'b',status:'applying'}]}];h.render();
 assert.match(h.text('save-chip-text'),/^Loading… 1 of 2$/);assert.equal(save.disabled,true);assert.equal(load.disabled,true);assert.equal(reason.hidden,true);
 // A place request of this lab.
 h.state.restore_jobs=[];h.context.busyText='';h.mem().placing='lab';h.render();assert.equal(save.disabled,true);assert.equal(reason.textContent,'The place to save is being set.');assert.equal(reason.hidden,false);
 h.mem().placing='';h.render();assert.equal(save.disabled,false);assert.equal(reason.hidden,true);
 // A lab without a save location keeps Save enabled: it opens the first-save view.
 h.state.labs=[freeLab()];h.state.git_jobs=[];h.context.busyText='A backup is running.';h.render();assert.equal(save.disabled,false);
});
test('Save on a lab with a save location posts the save once with an empty note and allow_removed, opens no dialog, and shows the saving view',async()=>{
 const h=harness({state:{git_jobs:[saved()]},routes:{'/git/save':payload=>({id:payload.request_id,lab_id:'lab',status:'queued',target:'latest',created:ago(0)})}});
 h.render();await h.context.gitSaveProgress();await h.flush();
 const posts=h.posts();assert.equal(posts.length,1);assert.equal(posts[0].endpoint,'/labs/lab/git/save');
 assert.equal(posts[0].payload.note,'');assert.equal(posts[0].payload.allow_removed,true);assert.equal(posts[0].payload.target,'latest');assert.equal(posts[0].payload.push,true);
 assert.deepEqual(h.dialogs,[]);assert.deepEqual(h.toasts,[],'no "Saving progress…" toast: the panel says it');
 assert.equal(h.panel.hidden,false);assert.equal(h.document.activeElement.id,'save-panel-title','focus is on the title before Save is disabled');
 assert.equal(h.text('save-chip-text'),'Saving…');assert.equal(h.text('save-panel-title-text'),'Saving…');assert.equal(h.el('git-save-progress').disabled,true);
 assert.match(h.body.innerHTML,/<p class="save-sub" id="save-saving">Reading the configuration of 4 devices\. You can keep working\.<\/p>/);
 assert.equal(h.el('save-change').disabled,true,'Change… is disabled while a save runs');
 checkMarkup(h.body.innerHTML,'saving');
 const sentence=status=>{h.state.git_jobs=[waiting({status,commit:status==='pushing'?'c1':'',...(status==='exporting-move'?{status:'exporting',target:'move'}:{})}),saved()];h.render();return h.body.innerHTML;};
 assert.match(sentence('exporting'),/Saving to the lab VM’s repository\. You can keep working\./);assert.match(sentence('exporting-move'),/Moving the saved files\. You can keep working\./);
 assert.match(sentence('pushing'),/Uploading to github\.com\. You can keep working\./);assert.equal(h.text('save-panel-title-text'),'Uploading…');
});
test('the moment between the click and the answer already reads Saving…, and a refused save becomes the Can’t save view of the chip, not a banner',async()=>{
 let release;const h=harness({state:{git_jobs:[saved()]},routes:{'/git/save':()=>new Promise((resolve,reject)=>{release=reject;})}});
 h.render();const pending=h.context.gitSaveProgress();await h.flush();
 assert.equal(h.text('save-chip-text'),'Saving…');assert.equal(h.el('save-chip-dot').className,'save-dot busy');assert.equal(h.el('git-save-progress').disabled,true);assert.match(h.body.innerHTML,/Reading the configuration of 4 devices/);
 release(Object.assign(new Error('Reconnect the original VM before saving progress.'),{status:409}));await pending;await h.flush();h.render();
 assert.equal(h.text('save-chip-text'),'Can’t save');assert.equal(h.text('save-panel-title-text'),'Can’t save');assert.equal(h.el('git-save-progress').disabled,false);
 assert.match(h.body.innerHTML,/id="save-cant-why">The save did not work\.</);assert.ok(h.el('save-cant-again'));assert.ok(h.el('save-cant-details'));
 // Closing the panel forgets the refusal.
 h.chip._menuClose(true);h.render();assert.equal(h.text('save-chip-text'),'Saved 21 min ago');
});
test('the upload view shows the sentence and the destination at once, enables Upload only when the review has arrived, and names every save the upload sends',async()=>{
 let answer;const h=harness({state:{git_jobs:[waiting(),saved()]},routes:{'/git/compare':()=>new Promise(resolve=>{answer=resolve;})}});
 h.chip._menuOpen();h.render();
 assert.equal(h.text('save-panel-title-text'),'Not uploaded yet');assert.equal(h.el('save-panel-dot').className,'save-dot warn');
 assert.match(h.body.innerHTML,/<p class="save-sub" id="save-changes">2 devices changed since your last save: ceos and xrv9k\. 19 lines added, 1 removed\.<\/p>/);
 assert.match(h.body.innerHTML,/<p class="save-kv" id="save-to"><span>To:<\/span> CLAB-MNGR-DEV-LLM › bgp<\/p>/);
 assert.equal(h.el('save-upload').disabled,true);assert.equal(h.el('save-checking').hidden,false);assert.match(h.body.innerHTML,/id="save-checking" role="status">Checking what this upload sends…</);
 assert.match(h.body.innerHTML,/id="save-upload" data-save-action="upload" disabled aria-describedby="save-checking"/,'the reason is the button’s description');
 for(const id of ['save-not-now','save-see','save-details'])assert.equal(h.el(id).disabled,false,id+' works while the review is read');
 assert.match(h.body.innerHTML,/<p class="save-note">Saved files can contain passwords or keys\.<\/p>/);
 assert.equal(h.posts().length,1,'one review request, however often the page renders');h.render();h.render();assert.equal(h.posts().length,1);
 checkMarkup(h.body.innerHTML,'upload, checking');
 h.el('save-not-now').focus();
 answer(review({also_sends:[{job_id:'a',lab:'bgp',name:'Start',kind:'',target:'latest'},{job_id:'b',lab:'ospf-lab',name:'ospf fixed',kind:'state',target:'latest'},{commit:'f'.repeat(40),name:'Save r1: first save',files:['r1.cfg']}]}));await h.flush();
 assert.match(h.body.innerHTML,/1 removed\. This upload also sends 3 other saves: Start \(bgp\), ospf fixed \(ospf-lab\) and &quot;Save r1: first save&quot;\.<\/p>/);
 assert.equal(h.el('save-upload').disabled,false);assert.equal(h.el('save-checking').hidden,true);
 assert.equal(h.document.activeElement,h.el('save-not-now'),'the rebuild hands focus back to the same control');
 checkMarkup(h.body.innerHTML,'upload');
});
test('a review that cannot be read shows its sentence with Try again and no Upload; an answer without a save at the newest commit says someone works in the repository',async()=>{
 let fail=true;const h=harness({state:{git_jobs:[waiting(),saved()]},routes:{'/git/compare':()=>fail?Object.assign(new Error('Cannot reach the VM Git helper.'),{status:409}):review({upload_job:null})}});
 await h.open();
 assert.match(h.body.innerHTML,/id="save-review-failed">What this upload sends could not be read from the lab VM\.</);assert.equal(h.el('save-upload'),null);assert.ok(h.el('save-review-again'));assert.ok(h.el('save-details'));
 assert.equal(h.posts().length,1);h.render();await h.flush();assert.equal(h.posts().length,1,'a failed review is not asked again by the poll');
 fail=false;await h.press('save-review-again');
 assert.equal(h.posts().length,2);assert.match(h.body.innerHTML,/id="save-review-busy">Someone is working in this repository on the VM\.</);assert.equal(h.el('save-upload'),null);assert.ok(h.el('save-review-again'));
 await assert.rejects(h.context.gitReviewJob(h.state.git_jobs[0],{upload:true}),/See what this upload sends before uploading\./);assert.equal(h.posts().filter(c=>c.endpoint.endsWith('/retry')).length,0);
 checkMarkup(h.body.innerHTML,'upload, no save at head');
});
test('Upload sends exactly one request to the retry route of the review’s upload_job with the head that was shown, also when that is another lab’s save',async()=>{
 const h=harness({state:{git_jobs:[waiting(),saved()]},routes:{'/git/compare':review({upload_job:'other-lab-job',head:'head-9',also_sends:[{job_id:'other-lab-job',lab:'ospf',name:'Newer',kind:'',target:'latest'}]}),'/retry':()=>({id:'other-lab-job',lab_id:'other',status:'queued',commit:'c9',created:ago(0)})}});
 await h.open();await h.press('save-upload');
 const uploads=h.posts().filter(c=>c.endpoint.endsWith('/retry'));assert.equal(uploads.length,1);assert.equal(uploads[0].endpoint,'/git/jobs/other-lab-job/retry');
 assert.equal(JSON.stringify(uploads[0].payload),'{"push":true,"reviewed":true,"head":"head-9"}');
 // The drawer's Upload is the same action and the same request; the drawer closes at once.
 const d=harness({state:{git_jobs:[waiting(),saved()]},routes:{'/git/compare':review(),'/retry':()=>waiting({status:'queued'})}});
 await d.context.gitReviewData(d.state.git_jobs[0]);await d.context.saveAction('upload',d.state.git_jobs[0],'drawer');
 const sent=d.posts().filter(c=>c.endpoint.endsWith('/retry'));assert.equal(sent.length,1);assert.equal(sent[0].endpoint,'/git/jobs/w/retry');assert.equal(JSON.stringify(sent[0].payload),'{"push":true,"reviewed":true,"head":"head-1"}');
 assert.deepEqual(d.drawers.map(x=>x.kind),['closed']);
});
test('no upload without the review of this save for the current set of waiting saves',async()=>{
 const h=harness({state:{git_jobs:[waiting(),saved()]},routes:{'/git/compare':review(),'/retry':()=>waiting({status:'queued'})}}),job=h.state.git_jobs[0];
 await assert.rejects(h.context.gitReviewJob(job,{upload:true}),/See what this upload sends before uploading\./);
 await h.context.gitReviewData(job);
 // Another save lands (a poll delivers it): the cached review no longer counts.
 h.state.git_jobs=[waiting({id:'x',lab_id:'other',commit:'c7'}),job,saved()];
 await assert.rejects(h.context.gitReviewJob(job,{upload:true}),/See what this upload sends before uploading\./);
 assert.equal(h.posts().filter(c=>c.endpoint.endsWith('/retry')).length,0,'nothing was posted');
 assert.equal(h.context.gitReviewCached(job),null);
});
test('gitReviewData caches per job until the waiting saves change and returns files, summary, head, upload_job and also_sends',async()=>{
 const h=harness({state:{git_jobs:[waiting(),saved()]},routes:{'/git/compare':payload=>review({files:[{name:'ceos.cfg'}],summary:{devices:['ceos'],added:1,removed:0},head:'h-'+payload.job_id})}}),job=h.state.git_jobs[0];
 const first=await h.context.gitReviewData(job);
 assert.deepEqual(Object.keys(first).sort(),['also_sends','files','head','summary','upload_job']);assert.equal(first.head,'h-w');assert.equal(first.upload_job,'w');assert.equal(first.files.length,1);
 assert.equal(await h.context.gitReviewData(job),first);assert.equal(h.posts().length,1);assert.deepEqual(JSON.parse(JSON.stringify(h.posts()[0].payload)),{job_id:'w'});
 const [a,b]=await Promise.all([h.context.gitReviewData(saved()),h.context.gitReviewData(saved())]);assert.equal(a,b);assert.equal(h.posts().length,2,'two callers share one request');
 h.state.git_jobs=[waiting({status:'committed'}),saved()];await h.context.gitReviewData(job);assert.equal(h.posts().length,3,'asked again when the set of waiting saves changed');
 await h.context.gitReviewData(job,{fresh:true});assert.equal(h.posts().length,4);
});
test('a save that landed after the review (409) empties the cache, shows the new review and the manager’s sentence, and uploads nothing until the next click',async()=>{
 let reviews=0,refuse=true;
 const h=harness({state:{git_jobs:[waiting(),saved()]},routes:{'/git/compare':()=>++reviews===1?review():review({head:'head-2',also_sends:[{job_id:'late',lab:'ospf',name:'Late save',kind:'',target:'latest'}]}),
  '/retry':()=>refuse?Object.assign(new Error('Another save was made in this repository. Look at the changes again.'),{status:409}):waiting({status:'queued'})}});
 await h.open();await h.press('save-upload');
 assert.equal(reviews,2,'the review was fetched again');assert.match(h.body.innerHTML,/This upload also sends 1 other save: Late save \(ospf\)\./);
 assert.match(h.body.innerHTML,/<p class="form-error" role="alert" id="save-panel-error">Another save was made in this repository\. Look at the changes again\.<\/p>/);
 assert.equal(h.posts().filter(c=>c.endpoint.endsWith('/retry')).length,1,'nothing more was sent by itself');assert.equal(h.el('save-upload').disabled,false);
 refuse=false;await h.press('save-upload');
 const uploads=h.posts().filter(c=>c.endpoint.endsWith('/retry'));assert.equal(uploads.length,2);assert.equal(uploads[1].payload.head,'head-2','the next click carries the new head');
});
test('the reviewed flag is written in exactly one place of the static scripts, gitReviewJob, and Start the repository is the only sender of initialize',()=>{
 const strip=text=>text.replace(/\/\*[\s\S]*?\*\//g,'').replace(/(^|[\s;{}),])\/\/.*$/gm,'$1');
 let reviewed=0,initialize=0;
 for(const name of fs.readdirSync(staticDir).filter(name=>name.endsWith('.js'))){const text=strip(read(name));reviewed+=(text.match(/reviewed\s*:\s*true/g)||[]).length;initialize+=(text.match(/initialize\s*:\s*true/g)||[]).length;}
 assert.equal(reviewed,1);assert.equal(initialize,1);
 const h=harness();
 assert.match(strip(h.context.gitReviewJob.toString()),/\{push:true,reviewed:true,head:review\.head\}/);
 assert.match(strip(h.context.saveFirstPlace.toString()),/kind==='start'\)body=saveStartBody\(body\)/);
 assert.match(strip(h.context.saveStartBody.toString()),/\{\.\.\.body,initialize:true\}/);
 // The folder chooser's Start the repository goes through the same function, behind a guard.
 assert.match(strip(read('save-drawers.js')),/case 'initialize':if\(typeof saveStartBody==='function'\)await drwChooserPlace\(c\.lastChoice,'',saveStartBody\(\{\}\)\)/);
});
test('gitReviewJob without upload posts nothing and opens the What changed drawer; See changes passes the chip as the opener',async()=>{
 const h=harness({state:{git_jobs:[waiting(),saved()]},routes:{'/git/compare':review()}});
 await h.context.gitReviewJob(h.state.git_jobs[0]);assert.equal(h.posts().length,0);assert.equal(h.drawers[0].kind,'changes');assert.equal(h.drawers[0].opts.job.id,'w');
 await h.open();await h.press('save-see');assert.equal(h.drawers[1].kind,'changes');assert.equal(h.drawers[1].opts.opener,h.chip);assert.equal(h.panel.hidden,true,'the panel closes first');
});
test('Not now sends no request, closes the panel, gives focus back to the chip and shows no toast',async()=>{
 const h=harness({state:{git_jobs:[waiting(),saved()]},routes:{'/git/compare':review()}});
 await h.open();const before=h.posts().length;await h.press('save-not-now');
 assert.equal(h.posts().length,before);assert.equal(h.panel.hidden,true);assert.deepEqual(h.toasts,[]);assert.equal(h.document.activeElement,h.chip);assert.equal(h.text('save-chip-text'),'1 save to upload');
 await h.context.saveAction('not-now',h.state.git_jobs[0],'drawer');assert.deepEqual(h.drawers.map(x=>x.kind),['closed']);assert.deepEqual(h.toasts,[]);
});
test('Details in the upload view and in the failed view opens the save window, which still offers Keep snapshot only, with focus returning to the chip',async()=>{
 for(const job of [waiting(),waiting({status:'push_pending',reviewed:'x',message:'The remote branch is unavailable. Check connectivity.'})]){
  const h=harness({state:{git_jobs:[job,saved()]},routes:{'/git/compare':review()}});
  const jobEls={'git-job-detail':{innerHTML:''},'git-job-actions':{innerHTML:'',querySelectorAll:()=>[]},'git-job-dialog':{open:true,querySelector:()=>null}};const lookup=h.context.$;h.context.$=id=>jobEls[id]||lookup(id);
  await h.open();await h.press('save-details');
  assert.equal(h.dialogs[0].id,'git-job-dialog');assert.equal(h.document.activeElement,h.chip,'the chip has focus when the window opens, so its close returns there');assert.equal(h.panel.hidden,true);
  assert.match(jobEls['git-job-actions'].innerHTML,/data-git-job-action="dismiss">Keep snapshot only/);
 }
});
test('the Upload failed view says what failed without claiming more, names every save the retry sends, and Try again is the same upload',async()=>{
 const failed=waiting({status:'push_pending',reviewed:'x',note:'ospf fixed',message:'The remote branch is unavailable. Check connectivity and try again.'});
 const h=harness({state:{git_jobs:[failed,saved()]},routes:{'/git/compare':review({also_sends:[{job_id:'a',lab:'bgp',name:'Start',kind:'',target:'latest'}]}),'/retry':()=>waiting({status:'queued'})}});
 h.chip._menuOpen();h.render();
 assert.equal(h.text('save-chip-text'),'Upload failed');assert.equal(h.text('save-panel-title-text'),'Upload failed');assert.equal(h.el('save-panel-dot').className,'save-dot bad');
 assert.match(h.body.innerHTML,/id="save-changes">Your save is safe on the lab VM, but github\.com could not be reached\.</);assert.equal(h.el('save-retry').disabled,true);assert.equal(h.el('save-not-now'),null);
 await h.flush();h.render();
 assert.match(h.body.innerHTML,/could not be reached\. This upload sends 2 saves: ospf fixed \(bgp\), Start \(bgp\)\.</);assert.equal(h.el('save-retry').disabled,false);assert.match(h.body.innerHTML,/id="save-retry" data-save-action="upload"[^>]*>Try again</);
 checkMarkup(h.body.innerHTML,'failed');
 await h.press('save-retry');const uploads=h.posts().filter(c=>c.endpoint.endsWith('/retry'));assert.equal(uploads.length,1);assert.equal(JSON.stringify(uploads[0].payload),'{"push":true,"reviewed":true,"head":"head-1"}');
 const other=harness({state:{git_jobs:[{...failed,message:'Git push failed. Check authentication.'},saved()]},routes:{'/git/compare':review()}});other.chip._menuOpen();other.render();
 assert.match(other.body.innerHTML,/Your save is safe on the lab VM, but it could not be uploaded to github\.com\./);
});
test('a waiting folder move reads as moved files, a checkpoint as kept, and a save that waits after a disconnect names where it goes',async()=>{
 const move=waiting({id:'m',target:'move',status:'committed',summary:undefined,note:'',destination:{...destination,path:'course/bgp'}});
 const h=harness({state:{git_jobs:[move,saved()]},routes:{'/git/compare':review({upload_job:'m'})}});await h.open();
 assert.match(h.body.innerHTML,/id="save-changes">bgp’s saved files moved to course\/bgp\.</);assert.match(h.body.innerHTML,/<span>To:<\/span> CLAB-MNGR-DEV-LLM › course\/bgp</);
 h.context.saveFinished(move);assert.equal(h.posts().filter(c=>c.endpoint.endsWith('/retry')).length,0,'a finished move never uploads by itself');
 const cp=harness({state:{git_jobs:[waiting({id:'k',target:'checkpoint',checkpoint:'ospf-up',captured:false,destination:{...destination,path:'bgp/checkpoints/ospf-up'}}),saved()]},routes:{'/git/compare':review({upload_job:'k'})}});await cp.open();
 assert.match(cp.body.innerHTML,/id="save-changes">Checkpoint ospf-up kept\. It is not uploaded yet\.</);assert.match(cp.body.innerHTML,/<span>To:<\/span> CLAB-MNGR-DEV-LLM › bgp</);
 // Disconnected: the upload view with To: from the job, no Saves to: line, and only Save as a lab state… in the foot.
 const gone=harness({lab:freeLab({name:'bgp'}),state:{git_jobs:[waiting({destination:{...destination,path:'latest'}})]},routes:{'/git/compare':review()}});await gone.open();
 assert.equal(gone.text('save-chip-text'),'1 save to upload');assert.match(gone.body.innerHTML,/<span>To:<\/span> CLAB-MNGR-DEV-LLM › top level</);assert.equal(gone.el('save-place'),null);
 assert.ok(gone.el('save-as-state'));assert.equal(gone.el('save-all'),null);assert.equal(gone.el('save-settings'),null);assert.equal(gone.el('save-upload').disabled,false);
});
test('saveFinished: nothing changed and uploaded are a toast; a waiting save, a failed upload and a stopped save open the panel once, never over a dialog or another menu, never for another lab or a design export',async()=>{
 let can=true;const h=harness({canOpen:()=>can,state:{git_jobs:[saved()]},routes:{'/git/compare':review()}});h.render();
 h.context.saveFinished(waiting({id:'u',status:'unchanged',pushed:true}));assert.deepEqual(h.toasts,['Nothing changed since your last save.']);assert.equal(h.panel.hidden,true);
 h.context.saveFinished(waiting({status:'synced',pushed:true,destination:{...destination,remote:'https://github.com/me/x.git'}}));assert.equal(h.toasts[1],'Uploaded to github.com.');assert.equal(h.panel.hidden,true);
 const job=waiting();h.state.git_jobs=[job,saved()];
 can=false;assert.equal(h.context.saveFinished(job),false);assert.equal(h.panel.hidden,true,'a dialog, a drawer or another menu is open: the chip alone changes');assert.equal(h.text('save-chip-text'),'1 save to upload');
 can=true;assert.equal(h.context.saveFinished({...job,lab_id:'other'}),false);assert.equal(h.context.saveFinished({...job,kind:'design'}),false);assert.equal(h.panel.hidden,true);
 const field={id:'device-filter',focus(){}};h.document.activeElement=field;
 assert.equal(h.context.saveFinished(job),true);assert.equal(h.panel.hidden,false);assert.equal(h.text('save-panel-title-text'),'Not uploaded yet');assert.equal(h.document.activeElement,field,'typing elsewhere is never interrupted');
 h.chip._menuClose(false);assert.equal(h.context.saveFinished(job),false,'not twice for the same result');assert.equal(h.panel.hidden,true);
 // Focus moves to the title when it was on the page body, the chip or Save.
 h.document.activeElement=h.el('git-save-progress');const failed={...job,status:'push_pending'};h.state.git_jobs=[failed,saved()];
 assert.equal(h.context.saveFinished(failed),true);assert.equal(h.document.activeElement.id,'save-panel-title');assert.equal(h.text('save-panel-title-text'),'Upload failed');
 // An upload that ends while its panel is open closes it; focus inside the panel goes back to the chip.
 h.state.git_jobs=[{...job,status:'synced',pushed:true},saved()];h.context.saveFinished(h.state.git_jobs[0]);assert.equal(h.panel.hidden,true);assert.equal(h.document.activeElement,h.chip);
 // The result of a save is shown even when the chip's state is another one (a checkpoint kept while a load is what runs).
 const load={id:'r',lab_id:'lab',status:'succeeded',created:ago(1),finished:ago(0.5),source:{type:'git',path:'bgp/checkpoints/ospf-up'},targets:[{node:'a',status:'verified'}]};
 const kept=waiting({id:'k',target:'checkpoint',checkpoint:'ospf-up',captured:false,finished:ago(0.2)});h.state.restore_jobs=[load];h.state.git_jobs=[kept,saved()];
 assert.equal(h.context.saveFinished(kept),true);assert.equal(h.text('save-chip-text'),'Running ospf-up');assert.equal(h.text('save-panel-title-text'),'Not uploaded yet');
 assert.match(h.body.innerHTML,/Also: this lab runs ospf-up\. <button[^>]*data-save-action="show-also"[^>]*>Show<\/button>/,'the state the view hides is one line away');
});
test('savePanelMarkup rebuilds only on a new key, keeps focus by id with the typed text and the caret, and sends focus to the title when the control is gone',()=>{
 const h=harness(),el=h.body;
 assert.equal(h.context.savePanelMarkup(el,'a',()=>'<input id="save-name" class="save-name" value="auto"><button type="button" id="save-x" data-save-action="x">X</button>'),true);
 assert.equal(h.context.savePanelMarkup(el,'a',()=>{throw new Error('not rebuilt');}),false);assert.equal(el.writes,1);
 const input=h.el('save-name');input.focus();input.value='my name';input.dataset.dirty='1';input.selectionStart=2;input.selectionEnd=5;
 h.context.savePanelMarkup(el,'b',()=>'<p id="save-x-why">now</p><input id="save-name" class="save-name" value="auto"><button type="button" id="save-x" data-save-action="x">X</button>');
 const next=h.el('save-name');assert.notEqual(next,input);assert.equal(h.document.activeElement,next);assert.equal(next.value,'my name');assert.equal(next.dataset.dirty,'1');assert.deepEqual(next.selection,[2,5]);
 h.el('save-x').focus();h.context.savePanelMarkup(el,'c',()=>'<p class="save-sub">gone</p>');
 assert.equal(h.document.activeElement.id,'save-panel-title','never to <body>');
});
test('the panel at rest: the name, Running, Uploaded, Saves to with Change…, Last load with Details, and the foot of three',async()=>{
 const load={id:'r',lab_id:'lab',status:'succeeded',created:ago(125),finished:ago(120),source:{type:'git',path:'course/start/latest'},targets:[{node:'a',status:'verified'}]};
 const h=harness({state:{git_jobs:[saved({note:'Interface descriptions cleaned up',note_auto:false})],restore_jobs:[load]}});const shown=[];h.context.restoreShowJob=async id=>shown.push(id);
 await h.open();
 assert.equal(h.text('save-panel-title-text'),'Saved 21 minutes ago');
 // PROMPT 5.3 step 7 (integration seam 6): the panel of a finished save shows its name in the editable field and Keep as a checkpoint,
 // whether the name is automatic or the person's own.
 assert.match(h.body.innerHTML,/^<label class="sr-only" for="save-name">Name of this save<\/label><input id="save-name" class="save-name" value="Interface descriptions cleaned up" maxlength="120" autocomplete="off" spellcheck="false">/);
 assert.match(h.body.innerHTML,/<label class="checkbox-label save-keep"><input type="checkbox" id="save-keep" data-save-action="keep"> Keep as a checkpoint<\/label>/);
 assert.match(h.body.innerHTML,/<span>Running:<\/span> your latest save/);assert.match(h.body.innerHTML,/<span>Uploaded:<\/span> yes, to github\.com/);
 assert.match(h.body.innerHTML,/<p class="save-kv" id="save-place"><span>Saves to:<\/span> CLAB-MNGR-DEV-LLM › bgp <button[^>]*id="save-change" data-save-action="place">Change…<\/button><\/p>/);
 assert.match(h.body.innerHTML,/<p class="save-kv" id="save-last-load"><span>Last load:<\/span> Start, 2 hours ago <button[^>]*id="save-load-details" data-save-action="load-details">Details<\/button><\/p>/);
 assert.match(h.body.innerHTML,/<div class="save-foot"><button[^>]*id="save-all"[^>]*>All versions<\/button><button[^>]*id="save-as-state"[^>]*>Save as a lab state…<\/button><button[^>]*id="save-settings"[^>]*>Save settings<\/button><\/div>$/);
 checkMarkup(h.body.innerHTML,'naming');
 await h.press('save-load-details');assert.deepEqual(shown,['r']);assert.equal(h.document.activeElement,h.chip);
 for(const [id,kind] of [['save-change','chooser'],['save-all','versions'],['save-as-state','state'],['save-settings','settings']]){await h.open();await h.press(id);const last=h.drawers[h.drawers.length-1];assert.equal(last.kind,kind);assert.equal(last.opts.opener,h.chip);assert.equal(h.panel.hidden,true);}
 // Without a load the line is not there; after a redeploy the manager no longer claims what runs; a save from before names existed.
 h.state.restore_jobs=[];h.state.operations=[{id:'o',lab_id:'lab',action:'redeploy',status:'succeeded',created:ago(10),finished:ago(9)}];h.state.git_jobs=[saved({note:'',note_auto:false})];await h.open();
 assert.equal(h.el('save-last-load'),null);assert.doesNotMatch(h.body.innerHTML,/Running:/);assert.match(h.body.innerHTML,/<input id="save-name" class="save-name" value="" /,'a save from before names existed has an empty field to name it in');
 // Kept on this VM.
 h.state.operations=[];h.state.git_jobs=[saved({status:'dismissed',pushed:false})];h.render();assert.equal(h.text('save-chip-text'),'Kept on this VM');assert.match(h.body.innerHTML,/<span>Uploaded:<\/span> no, kept on the lab VM/);
 assert.equal(h.el('save-name'),null,'a save that was put aside is plain text');assert.match(h.body.innerHTML,/<p class="save-sub" id="save-rest-name">[^<]+<\/p>/);checkMarkup(h.body.innerHTML,'rest');
});
test('the name of the latest save is an editable field: Enter commits once, an empty name returns to the automatic one, a failure keeps what was typed',async()=>{
 let fail=false;const h=harness({state:{git_jobs:[saved()]},routes:{'/name':payload=>fail?Object.assign(new Error('The name could not be stored.'),{status:500}):saved({note:payload.note||'ceos and xrv9k changed',note_auto:!payload.note})}});
 await h.open();
 assert.match(h.body.innerHTML,/<label class="sr-only" for="save-name">Name of this save<\/label><input id="save-name" class="save-name" value="ceos and xrv9k changed" maxlength="120" autocomplete="off" spellcheck="false">/);
 assert.match(h.body.innerHTML,/<label class="checkbox-label save-keep"><input type="checkbox" id="save-keep" data-save-action="keep"> Keep as a checkpoint<\/label>/);
 checkMarkup(h.body.innerHTML,'naming');
 const type=text=>{const input=h.el('save-name');input.focus();input.value=text;h.panel.listeners.input({target:input});return input;};
 let input=type('OSPF\tworks\n');let prevented=0;
 h.panel.listeners.keydown({key:'Enter',target:input,preventDefault(){prevented++;}});h.panel.listeners.change({target:input});await h.flush();
 const names=()=>h.posts().filter(c=>c.endpoint.endsWith('/name'));
 assert.equal(prevented,1);assert.equal(names().length,1,'Enter and the change event it causes commit once');assert.equal(names()[0].endpoint,'/git/jobs/s/name');assert.deepEqual(JSON.parse(JSON.stringify(names()[0].payload)),{note:'OSPF works'});
 assert.equal(h.text('save-live'),'Renamed.');assert.equal(h.panel.hidden,false,'Enter does not close the panel');assert.equal(h.state.git_jobs[0].note,'OSPF works');
 h.render();assert.ok(h.el('save-name'),'the field stays for the save being named in this panel session');assert.equal(h.el('save-name').value,'OSPF works');
 input=type('');h.panel.listeners.change({target:input});await h.flush();h.render();
 assert.deepEqual(JSON.parse(JSON.stringify(names()[1].payload)),{note:''});assert.equal(h.el('save-name').value,'ceos and xrv9k changed','the answer’s automatic name is shown');
 fail=true;input=type('Lost?');h.document.activeElement=h.document.body;h.panel.listeners.change({target:input});await h.flush();h.render();
 assert.equal(h.el('save-name').value,'Lost?','the typed text survives the failure and the rebuild');assert.match(h.body.innerHTML,/id="save-panel-error">The name could not be stored\.</);
 input=type('x'.repeat(121));h.panel.listeners.change({target:input});await h.flush();assert.equal(names().length,3,'too long is refused in the page');
 // After the panel closed, a save the person named keeps its field (PROMPT 5.3 step 7: both stay offered), with nothing typed left over.
 h.chip._menuClose(false);h.state.git_jobs=[saved({note:'OSPF works',note_auto:false})];await h.open();assert.match(h.body.innerHTML,/<input id="save-name" class="save-name" value="OSPF works" maxlength="120" autocomplete="off" spellcheck="false">/);assert.equal(h.el('save-rest-name'),null);assert.ok(h.el('save-keep'));
});
test('Keep as a checkpoint posts the save route with the save’s capture and an empty checkpoint name, and is disabled with its reason when the capture cannot be used',async()=>{
 const h=harness({state:{git_jobs:[saved()]},routes:{'/git/save':payload=>({id:payload.request_id,lab_id:'lab',status:'queued',target:'checkpoint',checkpoint:'ceos-and-xrv9k-changed',backup_job_id:'bk',captured:false,created:ago(0)})}});
 await h.open();const box=h.el('save-keep');assert.equal(box.disabled,false);box.checked=true;h.panel.listeners.change({target:box});await h.flush();
 const posts=h.posts();assert.equal(posts.length,1);assert.equal(posts[0].endpoint,'/labs/lab/git/save');
 const sent=posts[0].payload;assert.equal(sent.target,'checkpoint');assert.equal(sent.checkpoint,'');assert.equal(sent.backup_job_id,'bk');assert.equal(sent.push,true);assert.equal(sent.note,'ceos and xrv9k changed');assert.equal(sent.allow_removed,true);
 h.render();assert.equal(h.text('save-chip-text'),'Saving…');assert.match(h.body.innerHTML,/Saving to the lab VM’s repository\./,'no device is read for it');
 // Once it exists the box is ticked and disabled, with the name the manager gave.
 h.state.git_jobs=[{...h.state.git_jobs[0],status:'synced',pushed:true,commit:'c5',finished:ago(0)},saved()];h.render();
 assert.match(h.body.innerHTML,/<input type="checkbox" id="save-keep" data-save-action="keep" checked disabled aria-describedby="save-keep-why"> Keep as a checkpoint<\/label><p class="save-note" id="save-keep-why">Kept as checkpoint ceos-and-xrv9k-changed\.<\/p>/);
 for(const [more,why] of [[{capture_kept:false},'The capture of this save is no longer kept. Save again to make a checkpoint.'],[{capture_whole:false},'This capture does not include the topology. Save again first.']]){
  const d=harness({state:{git_jobs:[saved(more)]}});await d.open();
  assert.equal(d.el('save-keep').disabled,true);assert.match(d.body.innerHTML,new RegExp('aria-describedby="save-keep-why"> Keep as a checkpoint</label><p class="save-note" id="save-keep-why">'+why.replace(/\./g,'\\.')+'</p>'));
  d.panel.listeners.change({target:{...d.el('save-keep'),checked:false}});await d.flush();assert.equal(d.posts().length,0);checkMarkup(d.body.innerHTML,'naming, disabled');
 }
});
test('Can’t save shows one sentence and exactly the actions of its row',async()=>{
 const rows=[
  [{code:'vm'},[],'The lab VM could not be reached.',['again:Try again','vm:Check the VM connection…']],
  [{code:'account'},[],'The VM account cannot upload to github.com.',['again:Try again','details:Details']],
  [{code:'busy'},[],'Someone is working in this repository on the VM.',['again:Try again','details:Details']],
  [{code:'diverged'},[],'The online copy has changes this VM does not have.',['update:Update from the repository']],
  [{code:'diverged'},[waiting({id:'o',lab_id:'other',lab_name:'ospf'})],'The online copy and this VM both have changes the other does not have. They have to be combined on the VM.',['upload-again:Try again','details:Details']],
  [{code:'files'},[],'bgp holds files that were not saved by the manager.',['place:Choose another place','details:Details']],
  [{code:'settings'},[],'This lab’s save location has to be set up again.',['settings:Save settings','details:Details']],
  [{code:'devices'},[],'No device of this lab is selected for saving.',['settings:Save settings']],
  [{code:'other'},[],'The save did not work.',['again:Try again','details:Details']]];
 for(const [status,jobs,sentence,actions] of rows){
  const h=harness({lab:boundLab({git_status:{checked:true,ready:false,problem:'<raw helper text>',...status}}),state:{git_jobs:[...jobs,saved()]}});await h.open();
  assert.equal(h.text('save-chip-text'),'Can’t save',status.code);assert.equal(h.text('save-panel-title-text'),'Can’t save');assert.equal(h.el('save-panel-dot').className,'save-dot bad');
  assert.ok(h.body.innerHTML.includes('<p class="save-sub" id="save-cant-why">'+esc(sentence)+'</p>'),status.code+': '+sentence);
  const row=h.body.innerHTML.match(/<div class="save-row">(.*?)<\/div>/)[1];
  assert.deepEqual([...row.matchAll(/data-save-action="([\w-]+)"[^>]*>([^<]*)</g)].map(m=>m[1]+':'+m[2]),actions,status.code);
  // Both sides changed: what the repository's owner runs on the VM, as code with the lab's checkout path, each command on its own line.
  if(jobs.length)assert.match(h.body.innerHTML,/<p class="save-note" id="save-cant-how">The repository’s owner runs these on the lab VM, then Try again uploads the waiting saves:<\/p><pre class="git-setup-command" id="save-cant-commands" tabindex="0">git -C [^\n<]+ pull --no-rebase\ngit -C [^\n<]+ push<\/pre><div class="save-row">/);
  else assert.equal(h.el('save-cant-commands'),null);
  assert.match(row,/^<button type="button" class="button primary"/,'the first action is the primary one');assert.doesNotMatch(h.body.innerHTML,/raw helper text/,'the raw message is only under Details');
  checkMarkup(h.body.innerHTML,'cant '+status.code);
 }
 // A device that could not be read: its name, and Try again, Save settings, Details.
 const stopped=waiting({id:'x',status:'capture_incomplete',commit:'',message:'r1 unreachable',finished:ago(1)});
 const h=harness({state:{git_jobs:[stopped,saved()],jobs:[{id:'bk',lab_id:'lab',nodes:[{name:'clab-bgp-ceos',status:'failed'},{name:'n2',short_name:'xrv9k',status:'succeeded'}]}]}});await h.open();
 assert.match(h.body.innerHTML,/id="save-cant-why">ceos could not be read, so nothing was saved\.</);
 assert.deepEqual([...h.body.innerHTML.match(/<div class="save-row">(.*?)<\/div>/)[1].matchAll(/data-save-action="([\w-]+)"/g)].map(m=>m[1]),['again','settings','details']);
 await h.press('save-cant-settings');assert.equal(h.drawers[0].kind,'settings');
 const files=harness({lab:boundLab({git_status:{checked:true,ready:false,code:'files'}}),state:{git_jobs:[saved()]}});await files.open();await files.press('save-cant-place');assert.equal(files.drawers[0].kind,'chooser');assert.equal(files.drawers[0].opts.opener,files.chip);
 const vmLab=harness({lab:boundLab({git_status:{checked:true,ready:false,code:'vm'}}),state:{git_jobs:[saved()]}});let vmOpened=0;vmLab.context.openVmDialog=()=>{vmOpened++;};await vmLab.open();await vmLab.press('save-cant-vm');assert.equal(vmOpened,1);
 // Under Can't save the waiting upload is one line away.
 const also=harness({lab:boundLab({git_status:{checked:true,ready:false,code:'account'}}),state:{git_jobs:[waiting(),saved()]},routes:{'/git/compare':review()}});await also.open();
 assert.match(also.body.innerHTML,/<p class="save-note" id="save-also">Also: 1 save to upload\. <button[^>]*id="save-also-show" data-save-action="show-also">Show<\/button><\/p>/);
 await also.press('save-also-show');assert.equal(also.text('save-panel-title-text'),'Not uploaded yet');assert.match(also.body.innerHTML,/Also: saving is not possible right now\./,'and the way back is one line too');
});
test('Try again resumes from where the save stopped: a job that can be retried is retried, a lab state retries its own job, anything else is a new save',async()=>{
 const routes={'/retry':(payload,endpoint)=>waiting({id:endpoint.split('/')[3],status:'queued',commit:''}),'/git/save':payload=>({id:payload.request_id,lab_id:'lab',status:'queued',target:'latest',created:ago(0)})};
 const run=async job=>{const h=harness({state:{git_jobs:[job,saved()]},routes});await h.open();await h.press('save-cant-again');return h.posts();};
 let posts=await run(waiting({id:'e',status:'export_pending',commit:'',finished:ago(1)}));
 assert.deepEqual(posts.map(c=>c.endpoint),['/git/jobs/e/retry']);assert.equal(JSON.stringify(posts[0].payload),'{"push":false}');
 posts=await run(waiting({id:'st',kind:'state',status:'failed',commit:'',finished:ago(1)}));
 assert.deepEqual(posts.map(c=>c.endpoint),['/git/jobs/st/retry'],'never a save of the lab');
 posts=await run(waiting({id:'ci',status:'capture_incomplete',commit:'',finished:ago(1)}));
 assert.deepEqual(posts.map(c=>c.endpoint),['/labs/lab/git/save']);assert.equal(posts[0].payload.note,'');
 // A repository that was not ready: the status is read again and the save follows only when it is ready.
 for(const [status,expected] of [[{ready:true},['/labs/lab/git','/labs/lab/git/save']],[{ready:false,problem:'still busy'},['/labs/lab/git']]]){
  const h=harness({lab:boundLab({git_status:{checked:true,ready:false,code:'busy'}}),state:{git_jobs:[saved()]},routes:{...routes,'/labs/lab/git':(payload,endpoint)=>endpoint.endsWith('/git/save')?routes['/git/save'](payload):{binding,repository_status:status,jobs:[]}}});
  await h.open();await h.press('save-cant-again');assert.deepEqual(h.calls.map(c=>c.endpoint),expected);
 }
});
test('the first save on a lab without a save location: Save opens the panel and sends nothing; the panel’s Save places the lab with the acknowledgement, then saves',async()=>{
 const places={repositories:[{id:'reg',name:'CLAB-MNGR-DEV-LLM',remote:'https://github.com/me/x.git',path:CHECKOUT,current:false}],default:{repository:'reg',folder:'restore-square',answer:{kind:'free',folder:'restore-square',exists:false},ask:false,beside:''}};
 let release;const h=harness({lab:freeLab(),routes:{'/git/places':()=>places,'/git/place':()=>new Promise(resolve=>{release=resolve;}),'/git/save':payload=>({id:payload.request_id,lab_id:'lab',status:'queued',target:'latest',created:ago(0)})}});
 h.render();assert.equal(h.text('save-chip-text'),'Not saved yet');assert.equal(h.el('save-chip-dot').className,'save-dot none');
 await h.context.gitSaveProgress();
 assert.equal(h.posts().length,0);assert.equal(h.panel.hidden,false);assert.match(h.body.innerHTML,/<p class="save-sub" id="save-first-looking" role="status">Looking for a place to save…<\/p>/);
 checkMarkup(h.body.innerHTML,'first, looking');
 await h.flush();h.render();
 assert.equal(h.text('save-panel-title-text'),'Not saved yet');
 assert.match(h.body.innerHTML,/<p class="save-sub" id="save-first-place">Your first save goes to CLAB-MNGR-DEV-LLM, in a folder named restore-square\.<\/p>/,'a folder in no commit is never worded as being in the repository');
 assert.match(h.body.innerHTML,/id="save-first" data-save-action="first-save">Save<\/button><button[^>]*id="save-first-place-other" data-save-action="place">Choose another place</);
 assert.match(h.body.innerHTML,/<p class="save-note">Saved files can contain passwords or keys\.<\/p>/);assert.doesNotMatch(h.body.innerHTML,/type="checkbox"/,'no exposure tick box (D5)');
 assert.match(h.body.innerHTML,/<div class="save-foot"><button[^>]*id="save-as-state"[^>]*>Save as a lab state…<\/button><\/div>$/);assert.equal(h.el('save-place'),null);
 checkMarkup(h.body.innerHTML,'first');
 const click=h.press('save-first');await h.flush();h.render();
 // While the place request runs Save is disabled, with its reason.
 assert.equal(h.el('git-save-progress').disabled,true);assert.equal(h.text('save-reason'),'The place to save is being set.');assert.equal(h.text('save-panel-title-text'),'Saving…');assert.equal(h.el('save-first').disabled,true);
 h.state.labs=[boundLab({name:'restore-square'})];release({saved:true,binding,job:null,moved:false,move_reason:''});await click;await h.flush();h.render();
 const posts=h.posts();assert.deepEqual(posts.map(c=>c.endpoint),['/labs/lab/git/place','/labs/lab/git/save']);
 assert.deepEqual(JSON.parse(JSON.stringify(posts[0].payload)),{repository:'reg',folder:'restore-square',choice:'',pending:'',move_files:false,acknowledge:true});
 assert.equal(posts[1].payload.note,'');assert.equal(posts[1].payload.target,'latest');assert.equal(h.text('save-reason'),'');assert.equal(h.text('save-chip-text'),'Saving…');
 // The other wordings of the default place.
 const words=async(def,lab)=>{const d=harness({lab:lab||freeLab(),routes:{'/git/places':()=>({...places,default:{...places.default,...def}})}});await d.open();return d.body.innerHTML;};
 assert.match(await words({answer:{kind:'free',folder:'restore-square',exists:true}}),/Your first save goes to CLAB-MNGR-DEV-LLM, in the folder restore-square\./);
 assert.match(await words({folder:'',answer:{kind:'free',folder:'',exists:true}}),/Your first save goes to CLAB-MNGR-DEV-LLM, at its top level\./);
 assert.match(await words({answer:{kind:'own-before',folder:'restore-square',exists:true}}),/Your saves continue in CLAB-MNGR-DEV-LLM, in the folder restore-square\./);
 const attack=await words({folder:'<img>',answer:{kind:'free',folder:'<img>',exists:false}},freeLab({name:'<img src=x>'}));assert.doesNotMatch(attack,/<img/);assert.match(attack,/&lt;img&gt;/);
 assert.match(await words({},freeLab({nodes:[]})),/This lab has no device whose configuration can be saved\./);assert.doesNotMatch(await words({},freeLab({nodes:[]})),/data-save-action="first-save"/);
 // Choose another place hands the default place and the save that follows to the chooser.
 const c=harness({lab:freeLab(),routes:{'/git/places':()=>places,'/git/save':payload=>({id:payload.request_id,lab_id:'lab',status:'queued',created:ago(0)})}});await c.open();await c.press('save-first-place-other');
 assert.equal(c.drawers[0].kind,'chooser');assert.equal(c.drawers[0].opts.repository,'reg');assert.equal(c.drawers[0].opts.folder,'restore-square');assert.equal(c.drawers[0].opts.opener,c.chip);assert.equal(c.posts().length,0);
 await c.open();await c.press('save-as-state');assert.equal(c.drawers[1].kind,'state');assert.equal(c.drawers[1].opts.repository,'reg');
 await c.drawers[0].opts.then();assert.deepEqual(c.posts().map(x=>x.endpoint),['/labs/lab/git/save']);
});
test('a folder that holds saves of a lab with the same name is asked about once: Save in <name>-2 replaces nobody’s saves, Continue there takes the folder on purpose',async()=>{
 const places={repositories:[{id:'reg',name:'Course',path:CHECKOUT}],default:{repository:'reg',folder:'restore-square',answer:{kind:'state',folder:'restore-square',exists:true},ask:true,beside:'restore-square-2'}};
 const make=()=>harness({lab:freeLab(),routes:{'/git/places':()=>places,'/git/place':()=>({saved:true,binding,job:null}),'/git/save':payload=>({id:payload.request_id,lab_id:'lab',status:'queued',created:ago(0)})}});
 let h=make();await h.open();
 assert.match(h.body.innerHTML,/<p class="save-sub" id="save-first-place">This repository already holds saves of a lab named restore-square\.<\/p><div class="save-row"><button type="button" class="button primary" id="save-first" data-save-action="first-save">Save in restore-square-2<\/button><button type="button" class="button ghost small" id="save-first-continue" data-save-action="first-continue">Continue there<\/button><button type="button" class="button ghost small" id="save-first-url" data-save-action="connect-url">Connect by URL…<\/button><\/div>/);
 checkMarkup(h.body.innerHTML,'first, same name');
 await h.press('save-first');assert.deepEqual(JSON.parse(JSON.stringify(h.posts()[0].payload)),{repository:'reg',folder:'restore-square-2',choice:'',pending:'',move_files:false,acknowledge:true});
 h=make();await h.open();await h.press('save-first-continue');
 assert.deepEqual(JSON.parse(JSON.stringify(h.posts()[0].payload)),{repository:'reg',folder:'restore-square',choice:'take',pending:'',move_files:false,acknowledge:true});assert.equal(h.posts()[1].endpoint,'/labs/lab/git/save');
});
test('a question or a failure of the place request: the chooser takes over with the question, an outside failure is the Can’t save view, and Save is enabled again',async()=>{
 const places={repositories:[{id:'reg',name:'Course',path:CHECKOUT}],default:{repository:'reg',folder:'restore-square',answer:{kind:'free',folder:'restore-square',exists:false},ask:false,beside:''}};
 const question={kind:'lab',folder:'restore-square',lab:{id:'x',name:'other'}};
 const h=harness({lab:freeLab(),routes:{'/git/places':()=>places,'/git/place':()=>({question})}});await h.open();await h.press('save-first');
 assert.equal(h.drawers[0].kind,'chooser');assert.deepEqual(JSON.parse(JSON.stringify(h.drawers[0].opts.question)),question);assert.equal(typeof h.drawers[0].opts.then,'function');
 assert.equal(h.posts().length,1,'no save before the place is settled');assert.equal(h.el('git-save-progress').disabled,false);assert.doesNotMatch(h.body.innerHTML,/already|lab named/,'the panel never shows a folder question of its own');
 // A first save the VM refuses for a cause the manager recorded (lab.git_status of a lab without a save location, PROMPT 6.5): the
 // cause in words, Try again, the chooser one click away, and the manager's own sentence under Details in place.
 const v=harness({lab:freeLab({git_status:{checked:'t',ready:false,problem:'This checkout has commits that were not made by manager saves.',code:'busy',waiting:0}})});await v.open();
 assert.equal(v.text('save-chip-text'),'Can’t save');assert.match(v.body.innerHTML,/id="save-cant-why">Someone is working in this repository on the VM\.</);
 assert.deepEqual([...v.body.innerHTML.match(/<div class="save-row">(.*?)<\/div>/)[1].matchAll(/data-save-action="([\w-]+)"[^>]*>([^<]*)</g)].map(m=>m[1]+':'+m[2]),['again:Try again','place:Choose another place']);
 assert.match(v.body.innerHTML,/<details id="save-cant-details"><summary>Details<\/summary><p class="save-note">This checkout has commits that were not made by manager saves\.<\/p><\/details>/);
 const f=harness({lab:freeLab(),routes:{'/git/places':()=>places,'/git/place':()=>Object.assign(new Error('Cannot reach the VM Git helper.'),{status:409})}});await f.open();await f.press('save-first');
 assert.equal(f.text('save-chip-text'),'Can’t save');assert.match(f.body.innerHTML,/id="save-cant-why">The save did not work\.</);assert.equal(f.el('git-save-progress').disabled,false);assert.equal(f.text('save-reason'),'');
 await f.press('save-cant-again');assert.equal(f.text('save-chip-text'),'Not saved yet','Try again returns to the first save');
 // The places themselves cannot be read: never the address field.
 const p=harness({lab:freeLab(),routes:{'/git/places':()=>Object.assign(new Error('Connect the VM and verify its SSH host fingerprint first.'),{status:409})}});await p.open();
 assert.match(p.body.innerHTML,/id="save-cant-why">The lab VM could not be reached\.</);assert.equal(p.el('save-url'),null);assert.match(p.body.innerHTML,/id="save-panel-error">Connect the VM and verify its SSH host fingerprint first\.</);
 assert.ok(p.el('save-cant-again'));assert.ok(p.el('save-cant-vm'));checkMarkup(p.body.innerHTML,'first, places failed');
 const before=p.calls.length;await p.press('save-cant-again');await p.flush();assert.equal(p.calls.length,before+1,'Try again asks for the places again');
});
test('no repository on the VM: one field for the address, checked in the page; an empty repository asks once, and only Start the repository sends initialize',async()=>{
 let empty=true;const routes={'/git/places':()=>({repositories:[],default:null}),'/git/place':payload=>empty&&!payload.initialize?{question:{kind:'empty',name:'your-lab-repo'}}:{saved:true,binding,job:null},'/git/save':payload=>({id:payload.request_id,lab_id:'lab',status:'queued',created:ago(0)})};
 const h=harness({lab:freeLab(),routes});await h.open();
 assert.match(h.body.innerHTML,/<p class="save-sub">Your saves go to a repository on GitHub\. Paste its address; ask your instructor if you do not have one\.<\/p><label for="save-url">Repository address \(HTTPS\)<\/label><input id="save-url" class="save-name" value="" placeholder="https:\/\/github\.com\/you\/your-lab-repo" autocomplete="off" spellcheck="false" inputmode="url">/);
 assert.match(h.body.innerHTML,/The lab VM’s own GitHub login is used\. You are never asked for a password or a token here\./);assert.match(h.body.innerHTML,/Saved files can contain passwords or keys\. They go into a folder named restore-square\./);
 assert.match(h.body.innerHTML,/id="save-first" data-save-action="first-connect">Save</);checkMarkup(h.body.innerHTML,'first, address');
 const type=text=>{const input=h.el('save-url');input.value=text;h.panel.listeners.input({target:input});};
 type('git@github.com:you/repo.git');await h.press('save-first');
 assert.equal(h.posts().length,0);assert.match(h.body.innerHTML,/id="save-panel-error">Paste the HTTPS address, for example https:\/\/github\.com\/you\/your-lab-repo\.</);assert.equal(h.el('save-url').value,'git@github.com:you/repo.git','the typed address stays');
 type('https://github.com/you/your-lab-repo');await h.press('save-first');
 assert.deepEqual(JSON.parse(JSON.stringify(h.posts()[0].payload)),{url:'https://github.com/you/your-lab-repo',folder:'restore-square',choice:'',pending:'',move_files:false,acknowledge:true});assert.equal('initialize' in h.posts()[0].payload,false);
 assert.match(h.body.innerHTML,/<p class="save-sub" id="save-first-empty">your-lab-repo is empty\. The manager adds a README\.md file to start it\.<\/p><div class="save-row"><button type="button" class="button primary" id="save-first-start" data-save-action="first-start">Start the repository<\/button><\/div>/);
 assert.match(h.body.innerHTML,/<input id="save-url"[^>]* readonly>/);assert.equal(h.posts().length,1,'nothing is started without the click');checkMarkup(h.body.innerHTML,'first, empty repository');
 h.state.labs=[boundLab({name:'restore-square'})];await h.press('save-first-start');
 assert.deepEqual(JSON.parse(JSON.stringify(h.posts()[1].payload)),{url:'https://github.com/you/your-lab-repo',folder:'restore-square',choice:'',pending:'',move_files:false,acknowledge:true,initialize:true});
 assert.equal(h.posts()[2].endpoint,'/labs/lab/git/save');
 // A repository that cannot be connected explains itself in the manager's own words, and the address stays in the field.
 const f=harness({lab:freeLab(),routes:{...routes,'/git/place':()=>Object.assign(new Error('The VM account is not signed in to GitHub. Run gh auth login on the VM.'),{status:409})}});await f.open();
 const input=f.el('save-url');input.value='https://github.com/you/private';f.panel.listeners.input({target:input});await f.press('save-first');
 assert.match(f.body.innerHTML,/id="save-panel-error">The VM account is not signed in to GitHub\. Run gh auth login on the VM\.</);assert.equal(f.el('save-url').value,'https://github.com/you/private');assert.equal(f.el('save-first').disabled,false);assert.equal(f.text('save-chip-text'),'Not saved yet');
});
test('connected, nothing saved yet: the place is stated, Save is the ordinary save, the second button is Change… and the foot is the full one',async()=>{
 const h=harness({routes:{'/git/save':payload=>({id:payload.request_id,lab_id:'lab',status:'queued',target:'latest',created:ago(0)})}});await h.open();
 assert.equal(h.text('save-panel-title-text'),'Not saved yet');assert.match(h.body.innerHTML,/id="save-first-place">Your first save goes to CLAB-MNGR-DEV-LLM, in the folder bgp\.</);
 assert.match(h.body.innerHTML,/id="save-first-place-other" data-save-action="place">Change…</);assert.ok(h.el('save-all'));assert.ok(h.el('save-settings'));checkMarkup(h.body.innerHTML,'first, connected');
 h.context.busyText='A backup is running.';h.render();assert.equal(h.el('save-first').disabled,true);assert.match(h.body.innerHTML,/aria-describedby="save-first-why">Save<\/button>.*<p class="save-note" id="save-first-why">A backup is running\. Save is available when it finishes\.<\/p>/);
 h.context.busyText='';h.render();await h.press('save-first');assert.deepEqual(h.posts().map(c=>c.endpoint),['/labs/lab/git/save']);
});
test('the delegated listeners ignore what is not theirs: a disabled button, a click outside a control, and the panel’s views for a load come from load.js',async()=>{
 const h=harness({state:{git_jobs:[waiting(),saved()]},routes:{'/git/compare':()=>new Promise(()=>{})}});h.chip._menuOpen();h.render();
 const upload=h.el('save-upload');h.panel.listeners.click({target:{...upload,closest:()=>upload}});h.panel.listeners.click({target:{closest:()=>null}});await h.flush();
 assert.equal(h.posts().filter(c=>c.endpoint.endsWith('/retry')).length,0);
 const load={id:'r',lab_id:'lab',status:'succeeded',created:ago(1),finished:ago(0.5),source:{type:'git',path:'bgp/checkpoints/ospf-up'},targets:[{node:'a',status:'verified'}]};
 const l=harness({state:{git_jobs:[waiting({finished:ago(5)}),saved()],restore_jobs:[load]},routes:{'/git/compare':review()}});const seen=[];
 l.context.loadChipView=(cs,lab)=>{seen.push([cs.key,lab.id]);return {title:'Running ospf-up',dot:'info',key:'r',html:'<p class="save-sub" id="load-view">from load.js</p>'};};await l.open();
 assert.deepEqual(seen[0],['running','lab']);assert.equal(l.text('save-panel-title-text'),'Running ospf-up');assert.match(l.body.innerHTML,/^<p class="save-sub" id="load-view">from load\.js<\/p>/);
 assert.match(l.body.innerHTML,/<p class="save-note" id="save-also">Also: 1 save to upload\. <button/);
 await l.press('save-also-show');assert.equal(l.text('save-panel-title-text'),'Not uploaded yet');assert.equal(l.text('save-chip-text'),'Running ospf-up');
 // Without load.js the file still renders the lines it owns.
 const alone=harness({state:{git_jobs:[saved()],restore_jobs:[load]}});await alone.open();assert.equal(alone.text('save-panel-title-text'),'Running ospf-up');assert.ok(alone.el('save-all'));
});
test('save-header.js loads alone, without any other script, and renders nothing it cannot know',()=>{
 const context=vm.createContext({});vm.runInContext(read('save-header.js'),context);
 assert.equal(typeof context.renderSaveHeader,'function');assert.doesNotThrow(()=>context.renderSaveHeader());assert.equal(context.saveOpenPanel('status'),false);assert.equal(context.saveFinished(null),false);
 const source=read('save-header.js');
 assert.doesNotMatch(source,/\b(window|document|location|history)\.addEventListener|localStorage|sessionStorage/,'no global listener and no storage outside shell.js');
 assert.doesNotMatch(source.replace(/\.prefix\b/g,''),/\bregistration|\bprefix\b|\boverlap/i,'the words the design retires are in no sentence of this file');
});
// ---- S11 step 1: the gaps closed before the Progress tab goes ----
test('S11-1 (C-001) the header’s Save is wired by this file: without any Progress tab markup a click starts a save, and a disabled Save starts nothing',async()=>{
 const h=harness({state:{git_jobs:[saved()]},routes:{'/git/save':payload=>({id:payload.request_id,lab_id:'lab',status:'queued',target:'latest',created:ago(0)})}});
 assert.equal(h.el('git-progress-bar'),null,'the page of this test has no tab markup');
 const button=h.el('git-save-progress');assert.equal(typeof button.onclick,'function');
 h.render();await button.onclick();await h.flush();
 const sent=h.posts().filter(c=>c.endpoint.endsWith('/git/save'));assert.equal(sent.length,1);assert.equal(sent[0].payload.note,'');assert.equal(sent[0].payload.target,'latest');
 button.disabled=true;await button.onclick();await h.flush();assert.equal(h.posts().filter(c=>c.endpoint.endsWith('/git/save')).length,1);
 // A lab without a save location: Save opens the first-save view and sends nothing.
 const f=harness({lab:freeLab(),routes:{'/git/places':()=>({repositories:[],default:null})}});f.render();await f.el('git-save-progress').onclick();await f.flush();
 assert.equal(f.panel.hidden,false);assert.equal(f.posts().length,0);
});
test('S11-2 a save already running when the page loads is followed once, so its end reaches the header (the toast, the panel)',async()=>{
 const running=waiting({id:'run',status:'capturing',commit:''});
 const started=[],h=harness({state:{git_jobs:[running]}});
 const real=h.context.gitStartWatch;h.context.gitStartWatch=(job,options)=>{started.push([job.id,!!(options&&options.quiet)]);};
 h.render();h.render();h.render();
 assert.deepEqual(started.slice(0,1),[['run',true]],'followed quietly: the result is the chip panel’s');
 // With the real watch a second render starts nothing new.
 const g=harness({state:{git_jobs:[running]}});g.render();const first=vm.runInContext('gitWatch',g.context);g.render();
 assert.equal(first.id,'run');assert.equal(vm.runInContext('gitWatch',g.context),first,'once per job');assert.equal(first.quiet,true);
 // Home (no lab on screen) ends the watch.
 g.context.activeId='';g.context.renderSaveHeader(NOW);assert.equal(vm.runInContext('gitWatch',g.context),null);
});
test('S11-3 (C-025) Last load falls back to the lab’s newest finished load: one that changed no device reads "nothing changed" and its Details opens its job window',async()=>{
 const none={id:'r0',lab_id:'lab',status:'failed',created:ago(11),finished:ago(10),source:{type:'folder',path:'course/start/latest'},targets:[{name:'a',status:'failed'}]};
 const h=harness({state:{git_jobs:[saved()],restore_jobs:[none]}});const shown=[];h.context.restoreShowJob=async id=>shown.push(id);
 await h.open();
 assert.equal(h.text('save-chip-text'),'Saved 21 min ago','the chip’s own precedence does not change');
 assert.match(h.body.innerHTML,/<p class="save-kv" id="save-last-load"><span>Last load:<\/span> Start, nothing changed <button[^>]*id="save-load-details" data-save-action="load-details">Details<\/button><\/p>/);
 await h.press('save-load-details');assert.deepEqual(shown,['r0']);
 // A newer load that changed nothing is the one the line names; the older effective one stays in the chip when it still runs.
 const effective={id:'r1',lab_id:'lab',status:'succeeded',created:ago(125),finished:ago(120),source:{type:'folder',path:'course/final/latest'},targets:[{name:'a',status:'verified'}]};
 h.state.restore_jobs=[effective,none];await h.open();assert.match(h.body.innerHTML,/Last load:<\/span> Start, nothing changed /);
 h.state.restore_jobs=[effective];await h.open();assert.match(h.body.innerHTML,/Last load:<\/span> Final, 2 hours ago /);
});
test('S11-5, S11-7 the first-save view offers Connect by URL… (the chooser’s address field, the save follows) and says where uploads go',async()=>{
 const places={repositories:[{id:'reg',name:'Course',remote:'https://github.com/me/course.git',branch:'main',path:CHECKOUT,current:false}],default:{repository:'reg',folder:'restore-square',answer:{kind:'free',folder:'restore-square',exists:false},ask:false,beside:''}};
 const h=harness({lab:freeLab(),routes:{'/git/places':()=>places}});await h.open();
 assert.match(h.body.innerHTML,/id="save-first-place-other" data-save-action="place">Choose another place<\/button><button type="button" class="button ghost small" id="save-first-url" data-save-action="connect-url">Connect by URL…<\/button><\/div><p class="save-note" id="save-first-uploads">Uploads go to github\.com\/me\/course, branch main\.<\/p>/);
 await h.press('save-first-url');
 const drawer=h.drawers.at(-1);assert.equal(drawer.kind,'chooser');assert.equal(drawer.opts.mode,'location');assert.equal(drawer.opts.address,true);assert.equal(drawer.opts.folder,'restore-square');assert.equal(typeof drawer.opts.then,'function','the first save continues after the placement');
 assert.equal(h.posts().length,0);assert.equal(h.dialogs.length,0,'no dialog of the old connect route');
});
test('S11-12 both sides changed while saves wait: Try again uploads a reviewed waiting save only when the fresh review sends nothing the person was not shown; one not reviewed yet is shown first',async()=>{
 const job=waiting({id:'w',status:'push_pending',reviewed:ago(3)});
 const lab=boundLab({git_status:{checked:true,ready:false,problem:'The remote branch advanced or diverged.',code:'diverged',waiting:1}});
 // The person saw the failed upload's view (Show), with the review of that moment: this save alone.
 let rows=[];
 const routes={'/git/compare':()=>({files:[],head:'h1',upload_job:'w',also_sends:rows}),'/retry':payload=>({...job,status:'queued',sent:payload})};
 const h=harness({lab,state:{git_jobs:[job]},routes});
 await h.open();assert.equal(h.text('save-chip-text'),'Can’t save');assert.match(h.body.innerHTML,/id="save-cant-commands"[^>]*>git -C \/[^\n]+ pull --no-rebase\ngit -C \/[^\n]+ push<\/pre>/);
 await h.press('save-also-show');await h.flush();h.render();assert.equal(h.text('save-panel-title-text'),'Upload failed');assert.ok(h.mem().seen.get('lab').has('w'),'the view on screen is what was shown');
 h.mem().view=null;h.render();assert.equal(h.text('save-panel-title-text'),'Can’t save');
 await h.press('save-cant-upload-again');
 const retry=h.posts().filter(c=>c.endpoint.endsWith('/retry'));assert.equal(retry.length,1,'nothing new: it goes up with the fresh review');assert.deepEqual(JSON.parse(JSON.stringify(retry[0].payload)),{push:true,reviewed:true,head:'h1'});
 // P2-1: a save of another lab landed in the repository since that review. The fresh review names it; the person has not seen it:
 // nothing is uploaded, the waiting view shows the new sentence, and Upload there sends it.
 rows=[];
 const g=harness({lab,state:{git_jobs:[job]},routes});
 await g.open();await g.press('save-also-show');await g.flush();g.render();g.mem().view=null;g.render();
 rows=[{job_id:'o',lab:'ospf',name:'Landed meanwhile',kind:'capture',target:'latest'}];
 await g.press('save-cant-upload-again');await g.flush();g.render();
 assert.equal(g.posts().filter(c=>c.endpoint.endsWith('/retry')).length,0,'a save nobody was shown is never uploaded by Try again');
 assert.equal(g.text('save-panel-title-text'),'Upload failed');assert.match(g.body.innerHTML,/This upload sends 2 saves: [^<]*Landed meanwhile \(ospf\)\./,'it is named first');
 await g.press('save-retry');assert.equal(g.posts().filter(c=>c.endpoint.endsWith('/retry')).length,1,'and goes up with the click that follows the sentence');
 // A row known only by its commit (a commit the manager holds no save for) counts the same.
 rows=[];
 const k=harness({lab,state:{git_jobs:[job]},routes});
 await k.open();await k.press('save-also-show');await k.flush();k.render();k.mem().view=null;k.render();
 rows=[{commit:'9c1e2aa',name:'Edited by hand'}];
 await k.press('save-cant-upload-again');await k.flush();assert.equal(k.posts().filter(c=>c.endpoint.endsWith('/retry')).length,0);
 // Never shown at all on this page (the review flag came from another browser): shown first.
 const n=harness({lab,state:{git_jobs:[job]},routes});
 await n.open();await n.press('save-cant-upload-again');await n.flush();n.render();
 assert.equal(n.posts().filter(c=>c.endpoint.endsWith('/retry')).length,0);assert.equal(n.text('save-panel-title-text'),'Upload failed');
 const u=harness({lab,state:{git_jobs:[waiting({id:'w2',status:'review_pending'})]},routes:{'/git/compare':()=>({files:[],head:'h1',upload_job:'w2',also_sends:[]})}});
 await u.open();await u.press('save-cant-upload-again');await u.flush();u.render();
 assert.equal(u.posts().filter(c=>c.endpoint.endsWith('/retry')).length,0,'a save the person has not reviewed is never uploaded from here');assert.equal(u.text('save-panel-title-text'),'Not uploaded yet');
});
test('P2-3 a lab without a save location whose devices are all of an unsupported kind: the first Save is off with the reason; one supported device is enough',async()=>{
 const places={'/git/places':()=>({repositories:[{id:'r',name:'Course',remote:'https://github.com/me/course.git',branch:'main'}],default:{repository:'r',folder:'restore-square',answer:{kind:'free',exists:false}}})};
 const lab=freeLab({nodes:[{name:'h1',platform:'linux'},{name:'h2',platform:''}]});
 const h=harness({lab,state:{platforms:{eos:{label:'EOS'}}},routes:places});await h.open();
 assert.equal(h.el('save-first').disabled,true);assert.match(h.body.innerHTML,/<p class="save-sub" id="save-first-none">This lab has no device whose configuration can be saved\.<\/p>/);
 assert.match(h.body.innerHTML,/id="save-first"[^>]*disabled[^>]*aria-describedby="save-first-none"/);
 const ok=harness({lab:freeLab({nodes:[{name:'h1',platform:'linux'},{name:'r1',platform:'eos'}]}),state:{platforms:{eos:{label:'EOS'}}},routes:places});await ok.open();
 assert.equal(ok.el('save-first').disabled,false);assert.doesNotMatch(ok.body.innerHTML,/save-first-none/);
});
test('P2-4 a VM without a repository: the administrator’s setup is folded under the address field, and Check again reads the repositories anew',async()=>{
 let repositories=[];
 const h=harness({lab:freeLab(),routes:{'/git/places':()=>({repositories,default:repositories.length?{repository:'r',folder:'restore-square',answer:{kind:'free',exists:false}}:null})}});await h.open();
 assert.match(h.body.innerHTML,/<details id="save-first-admin"><summary>Administrator setup \(terminal\)<\/summary>/);assert.doesNotMatch(h.body.innerHTML,/<details id="save-first-admin" open/,'folded');
 assert.match(h.body.innerHTML,/On the VM, run this as your normal account \(no sudo\)\. It sets up the checkout and Git login\. Then click Check again\./);assert.match(h.body.innerHTML,/<pre class="git-setup-command" id="save-first-admin-command">bash deploy\/setup-git\.sh<\/pre>/);
 const asked=h.calls.filter(c=>c.endpoint.endsWith('/git/places')).length;
 repositories=[{id:'r',name:'Course',remote:'https://github.com/me/course.git',branch:'main'}];
 await h.press('save-first-check');await h.flush();h.render();
 assert.equal(h.calls.filter(c=>c.endpoint.endsWith('/git/places')).length,asked+1);assert.match(h.body.innerHTML,/Your first save goes to Course, in a folder named restore-square\./);assert.equal(h.el('save-url'),null);
});
test('Q390-07 a disconnected lab that has earlier saves: the chip keeps Saved, and the view says the lab has no save location now and where the next save goes',async()=>{
 const places={'/git/places':()=>({repositories:[{id:'r',name:'Course',remote:'https://github.com/me/course.git',branch:'main'}],default:{repository:'r',folder:'restore-square',answer:{kind:'free',exists:false}}})};
 const h=harness({lab:freeLab(),state:{git_jobs:[saved()]},routes:places});await h.open();
 assert.match(h.text('save-chip-text'),/^Saved /);
 assert.match(h.body.innerHTML,/<p class="save-sub" id="save-first-place">This lab has no save location now\. Your next save goes to Course, in a folder named restore-square\.<\/p>/);assert.doesNotMatch(h.body.innerHTML,/Your first save/);
 const fresh=harness({lab:freeLab(),routes:places});await fresh.open();assert.match(fresh.body.innerHTML,/Your first save goes to Course, in a folder named restore-square\./);
 const own=harness({lab:freeLab(),state:{git_jobs:[saved()]},routes:{'/git/places':()=>({repositories:[{id:'r',name:'Course'}],default:{repository:'r',folder:'restore-square',answer:{kind:'own-before',exists:true}}})}});await own.open();
 assert.match(own.body.innerHTML,/Your saves continue in Course, in the folder restore-square\./);
});
test('Q1440-11 one state, one name: an upload refused because both sides changed opens on the chip’s Can’t save, with the failed upload behind Show; Q390-12 a view that offers Save settings does not offer it twice',async()=>{
 const job=waiting({id:'w',status:'push_pending',reviewed:ago(3)});
 const lab=boundLab({git_status:{checked:true,ready:false,problem:'The remote branch advanced or diverged.',code:'diverged',waiting:1}});
 const h=harness({lab,state:{git_jobs:[job]},routes:{'/git/compare':()=>({files:[],head:'h1',upload_job:'w',also_sends:[]})}});
 assert.equal(h.context.saveFinished(job),true);h.render();await h.flush();h.render();
 assert.equal(h.text('save-chip-text'),'Can’t save');assert.equal(h.text('save-panel-title-text'),'Can’t save','the panel names the state as the chip does');
 assert.match(h.body.innerHTML,/Also: the last upload failed\. <button[^>]*data-save-action="show-also"/);
 await h.press('save-also-show');assert.equal(h.text('save-panel-title-text'),'Upload failed','asked for, it is shown and stays');h.render();assert.equal(h.text('save-panel-title-text'),'Upload failed');
 // any other failed upload keeps its own name
 const plain=harness({state:{git_jobs:[job]},routes:{'/git/compare':()=>({files:[],head:'h1',upload_job:'w',also_sends:[]})}});
 assert.equal(plain.context.saveFinished(job),true);plain.render();assert.equal(plain.text('save-chip-text'),'Upload failed');assert.equal(plain.text('save-panel-title-text'),'Upload failed');
 // Q390-12
 const none=harness({lab:boundLab({git_status:{checked:true,ready:false,problem:'No device of this lab is selected for saving.',code:'devices',waiting:0}}),state:{git_jobs:[saved()]}});await none.open();
 assert.equal(none.text('save-panel-title-text'),'Can’t save');assert.equal((none.body.innerHTML.match(/>Save settings<\/button>/g)||[]).length,1);
 const rest=harness({state:{git_jobs:[saved()]}});await rest.open();assert.equal((rest.body.innerHTML.match(/>Save settings<\/button>/g)||[]).length,1);
});
test('Q390-05 a name being typed is never posted by the poll: a change fired by the rebuild of the panel is ignored, the caret stays where it is, Enter and a real change commit',async()=>{
 const job=saved({note:'abcdefgh'});
 const h=harness({state:{git_jobs:[job]},routes:{'/name':payload=>({...job,note:payload.note})}});await h.open();
 const field=h.el('save-name');field.focus();field.value='abcdXefgh';field.selectionStart=5;field.selectionEnd=5;field.isConnected=true;
 h.panel.listeners.input({target:field});
 // The poll rebuilds the panel (something in it changed); the browser fires `change` on the removed field while it does.
 const write=Object.getOwnPropertyDescriptor(h.body,'innerHTML');
 Object.defineProperty(h.body,'innerHTML',{configurable:true,get:write.get,set(html){field.isConnected=false;h.panel.listeners.change({target:field});write.set.call(this,html);}});
 h.state.git_jobs=[{...job,finished:ago(40)}];h.body._listKey='stale';h.render();await h.flush();
 assert.equal(h.posts().filter(c=>c.endpoint.endsWith('/name')).length,0,'the poll never posts a rename');
 const now=h.el('save-name');assert.notEqual(now,field);assert.equal(now.value,'abcdXefgh','the typed text is kept');assert.deepEqual(now.selection,[5,5],'and the caret');assert.equal(h.document.activeElement,now);
 // A change that arrives late for the removed field (asynchronously) is ignored too.
 h.panel.listeners.change({target:field});await h.flush();assert.equal(h.posts().filter(c=>c.endpoint.endsWith('/name')).length,0);
 // A field that was not edited keeps its caret across a rebuild as well.
 now.dataset.dirty='';now.selectionStart=3;now.selectionEnd=3;h.body._listKey='stale2';h.render();assert.deepEqual(h.el('save-name').selection,[3,3]);
 // The person commits: a real change (the field lost focus, it is still in the page) or Enter.
 const live=h.el('save-name');live.value='Named by hand';live.isConnected=true;h.panel.listeners.change({target:live});await h.flush();
 assert.deepEqual(h.posts().filter(c=>c.endpoint.endsWith('/name')).map(c=>c.payload.note),['Named by hand']);
});
test('Q390-01 the view asked for with Show stays: the end of the upload that arrives after the click does not flip the panel back; it ends when the panel closes or its state ends',async()=>{
 const job=waiting({id:'w',status:'push_pending',reviewed:ago(3)});
 const lab=boundLab({git_status:{checked:true,ready:false,problem:'The remote branch advanced or diverged.',code:'diverged',waiting:1}});
 const h=harness({lab,state:{git_jobs:[job]},routes:{'/git/compare':()=>({files:[],head:'h1',upload_job:'w',also_sends:[]})}});
 // The upload failed: the panel is on Upload failed, the poll already turned the chip to Can't save with its Also line.
 await h.open();h.mem().view={lab:'lab',panel:'failed',job:'w'};h.render();await h.flush();h.render();
 // (Before Q1440-11 the panel stayed on Upload failed here and Show led to the Can't save view; the state now has one name.)
 assert.equal(h.text('save-panel-title-text'),'Can’t save');assert.match(h.body.innerHTML,/Also: the last upload failed\./);
 // A view asked for with Show, here the running load's or any other, is kept the same way: ask for the failed upload and back.
 await h.press('save-also-show');assert.equal(h.text('save-panel-title-text'),'Upload failed');
 assert.equal(h.context.saveFinished({...job}),false);h.render();assert.equal(h.text('save-panel-title-text'),'Upload failed','the end of the upload does not replace a view the person asked for');
 await h.press('save-also-show');assert.equal(h.text('save-panel-title-text'),'Can’t save');
 // The watch of the upload answers only now.
 assert.equal(h.context.saveFinished(job),false);h.render();
 assert.equal(h.text('save-panel-title-text'),'Can’t save','the view the person asked for is still shown');assert.match(h.body.innerHTML,/id="save-cant-commands"/);
 for(let i=0;i<3;i++)h.render();assert.equal(h.text('save-panel-title-text'),'Can’t save','and every poll after it');
 // Its state ends (the status is ready again): the chip's own view returns.
 h.state.labs[0]={...lab,git_status:{checked:true,ready:true,problem:'',code:'',waiting:1}};h.render();assert.equal(h.text('save-panel-title-text'),'Upload failed');
 // Closing the panel forgets the asked view; a result that arrives while no view was asked for opens on itself as before.
 const g=harness({lab,state:{git_jobs:[job]},routes:{'/git/compare':()=>({files:[],head:'h1',upload_job:'w',also_sends:[]})}});
 await g.open();assert.equal(g.text('save-panel-title-text'),'Can’t save');
 assert.equal(g.context.saveFinished(job),true);g.render();assert.equal(g.text('save-panel-title-text'),'Can’t save','both sides changed: the one name (Q1440-11)');
 g.state.labs[0]={...lab,git_status:{checked:true,ready:true,problem:'',code:'',waiting:1}};g.render();assert.equal(g.text('save-panel-title-text'),'Upload failed','any other failed upload opens on itself');
 g.chip._menuClose(false);assert.equal(g.mem().view,null);
});

test('Keep as a checkpoint sends nothing when the save has no capture id (the manager would read the devices again and write latest too)',async()=>{
 const h=harness({state:{git_jobs:[saved()]},routes:{'/git/save':()=>{throw new Error('must not be posted');}}});
 await h.open();const box=h.el('save-keep');assert.equal(box.disabled,false);
 h.state.git_jobs[0].backup_job_id='';   // the capture went between the render and the click
 box.checked=true;h.panel.listeners.change({target:box});await h.flush();
 assert.equal(h.posts().length,0,'nothing is posted');
 assert.match(h.body.innerHTML,/The capture of this save is no longer kept\. Save again to make a checkpoint\./);
});
