'use strict';
// The lab builder's editable YAML panel (requirement C4). The text drives the same editing engine as the
// canvas through the adapter's handle (lab-builder/src/main.tsx: applyYaml, getYaml, checkYaml, locateYaml, subscribe):
// there is no second topology model here. Apply replaces the whole topology as one engine step, so the
// editor's own Undo takes it back; a refused text stays in the panel and the graph is untouched.
// Visual edits refresh the text only while the student has no unapplied edits of their own; otherwise the
// panel says the canvas changed and Revert loads it. Nothing here reads the YAML: syntax and shape checks
// are the adapter's (the bundled parser), the located tree it hands over is checked by lab-builder-check.js
// (docs/parity-campaign/C08-DESIGN.md section 4), so this file needs no library and loads in Node for its tests.
// The Problems list, the gutter marks and the key help are advice: they never stop Apply or Save.
const BUILDER_YAML_DELAY=400;
const BUILDER_YAML_KEY_DELAY=150;
const BUILDER_YAML_NARROW='(max-width: 900px)';
const BUILDER_YAML_TEXT={edited:'Edited · not applied',applying:'Applying…',applied:'Applied',appliedNewer:'Applied · newer edits not applied',canvas:'Canvas changed · Revert to load it',reverted:'Reverted to the editor’s topology',nothing:'Nothing to apply',closeDirty:'Apply or Revert your edits before closing with Escape.',notReady:'The editor is not ready yet: the text is read-only for now.',
 problemsNote:'These do not stop Apply or Save; containerlab refuses errors when the lab is deployed.',notChecked:'Not checked: fix the error above first',settingsPending:'(settings not checked yet)',
 schemaFailed:'The topology schema could not be loaded from the manager, so settings and kinds are not checked; links and boot order still are.'};
// The boot-order example of the help (docs/parity-campaign/C08-DESIGN.md section 4.5): a switch first, the router after it is healthy.
const BUILDER_YAML_EXAMPLE=['name: juniper-pair','topology:','  nodes:','    vsw:','      kind: juniper_vjunosswitch','      image: n24l/vjunos-switch:23.2R1.14','    vrt:','      kind: juniper_vjunosrouter','      image: n24l/juniper_vjunos-router:26.2R1.7','      stages:','        create:','          wait-for:','            - node: vsw','              stage: healthy','  links:','    - endpoints: ["vsw:ge-0/0/0", "vrt:ge-0/0/0"]',''].join('\n');
const builderYaml={open:false,dirty:false,applying:false,canvasChanged:false,base:'',status:'',tone:'',editor:null,getDraftYaml:null,onApplied:null,onToggle:null,unsubscribe:null,timer:null,lines:0,
 // The Problems list: the newest located tree and its text, the gutter marks (line -> {severity,message}), the errors listed, the count sentence last written.
 tree:null,treeText:'',marks:new Map(),markSig:'',builtSig:'',listErrors:0,countText:'',countTone:'',keyTimer:null,
 // The containerlab version the VM reported (builderYamlContext) and the schema fetch: idle (null), loading, ready or failed, per schema version.
 vmVersion:'',schemaState:null,bound:false};
function builderYamlEscape(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
// The example with its Copy button (clipboard.js, when the page loaded it). It is a sibling of the help paragraph, never inside an aria-describedby target.
function builderYamlExampleMarkup(){
 const copy=typeof copyButton==='function'?copyButton(BUILDER_YAML_EXAMPLE,'the boot order example','','Copy example'):'';
 return `<details class="builder-yaml-example" id="builder-yaml-example"><summary>Boot order: start the router after the switch is healthy (stages)</summary>`
  +`<p class="form-help">On a VM with little memory, start one VM-based device at a time: the router’s container is created only when the switch reports healthy. <code>healthy</code> works for devices with a health check (vJunos-switch, vJunos-router, XRv9k); for cEOS or cJunosEvolved wait for <code>create-links</code> instead. Copy the <code>stages:</code> block under the device that should wait; the images are this course’s, use your own.</p>`
  +`<pre class="builder-yaml-example-code"><code>${builderYamlEscape(BUILDER_YAML_EXAMPLE)}</code></pre><div class="builder-yaml-example-actions">${copy}</div></details>`;
}
// A line-number gutter scrolled with the text: wrap="off" keeps one text line per gutter line, so the numbers
// stay right as long as both share the font and line height (lab-builder.css). It is aria-hidden: the
// Problems list names the line in words, which is what a screen reader needs.
function builderYamlPanelMarkup(){
 return `<aside id="builder-yaml-panel" class="builder-yaml-panel" hidden aria-labelledby="builder-yaml-title">`
  +`<div class="builder-yaml-head"><h2 id="builder-yaml-title">Topology YAML</h2>`
  +`<button type="button" class="button primary" id="builder-yaml-apply" title="Apply (Ctrl+Enter)" aria-keyshortcuts="Control+Enter" disabled>Apply</button>`
  +`<button type="button" class="button secondary" id="builder-yaml-revert" disabled>Revert</button>`
  +`<button type="button" class="icon-button" id="builder-yaml-close" aria-label="Close the YAML panel">×</button></div>`
  +`<p class="form-help builder-yaml-help" id="builder-yaml-help">Edit the topology as text, then Apply (Ctrl+Enter). The map follows, and the editor’s Undo takes an apply back.</p>`
  +builderYamlExampleMarkup()
  +`<div class="builder-yaml-body"><pre class="builder-yaml-gutter" id="builder-yaml-gutter" aria-hidden="true">1</pre>`
  +`<textarea id="builder-yaml-editor" class="builder-yaml-editor" spellcheck="false" wrap="off" autocapitalize="off" autocomplete="off" aria-label="Topology YAML" aria-describedby="builder-yaml-status builder-yaml-help builder-yaml-count"></textarea></div>`
  +`<p id="builder-yaml-status" class="builder-yaml-status" role="status" aria-live="polite"></p>`
  +`<section class="builder-yaml-problems" id="builder-yaml-problems" aria-labelledby="builder-yaml-problems-title">`
  +`<h3 id="builder-yaml-problems-title" class="builder-yaml-problems-title">Problems <span id="builder-yaml-count" role="status" aria-live="off"></span></h3>`
  +`<p id="builder-yaml-announce" class="sr-only" role="status" aria-live="polite"></p>`
  +`<p class="form-help builder-yaml-problems-note" id="builder-yaml-problems-note">${builderYamlEscape(BUILDER_YAML_TEXT.problemsNote)}</p>`
  +`<p class="builder-yaml-schema-failed" id="builder-yaml-schema-failed" hidden>${builderYamlEscape(BUILDER_YAML_TEXT.schemaFailed)} <button type="button" class="button secondary" id="builder-yaml-schema-retry">Try again</button></p>`
  +`<ol id="builder-yaml-list" class="builder-yaml-list"></ol>`
  +`<details class="builder-yaml-more" id="builder-yaml-more" open><summary>About this check</summary>`
  +`<p id="builder-yaml-schema" class="form-help builder-yaml-schema"></p><p id="builder-yaml-keyhelp" class="form-help builder-yaml-keyhelp" aria-live="off"></p></details></section></aside>`;
}
function builderYamlEl(id){return typeof document==='undefined'?null:document.getElementById(id);}
function builderYamlMake(tag,className,text){const el=document.createElement(tag);if(className)el.className=className;if(text!==undefined)el.textContent=text;return el;}
function builderYamlReady(){return !!(builderYaml.editor&&typeof builderYaml.editor.applyYaml==='function');}
// The engine's text as of its last settled operation; before the editor is attached, the stored draft.
function builderYamlCurrent(){const e=builderYaml.editor;if(e&&typeof e.getYaml==='function')return String(e.getYaml()??'');return builderYaml.getDraftYaml?String(builderYaml.getDraftYaml()??''):'';}
function builderYamlText(){const box=builderYamlEl('builder-yaml-editor');return box?box.value:builderYaml.base;}
// aria-invalid: a blocking error in the status line, or an error in the Problems list.
function builderYamlInvalid(){const box=builderYamlEl('builder-yaml-editor');if(box)box.setAttribute('aria-invalid',builderYaml.tone==='error'||builderYaml.listErrors>0?'true':'false');}
function builderYamlShow(text,tone){
 builderYaml.status=text||'';builderYaml.tone=tone||'';
 const line=builderYamlEl('builder-yaml-status');if(line){line.textContent=builderYaml.status;line.className='builder-yaml-status'+(builderYaml.tone?' is-'+builderYaml.tone:'');}
 builderYamlInvalid();
}
function builderYamlButtons(){
 const apply=builderYamlEl('builder-yaml-apply'),revert=builderYamlEl('builder-yaml-revert'),box=builderYamlEl('builder-yaml-editor');
 if(apply)apply.disabled=!builderYamlReady()||builderYaml.applying||!builderYaml.dirty;
 if(revert)revert.disabled=builderYaml.applying||!(builderYaml.dirty||builderYaml.canvasChanged);
 if(box)box.readOnly=!builderYamlReady();
}
// One <span> per text line, separated by newlines inside the <pre>, so the gutter reads 1, 2, 3 … line by line; a line with a finding
// carries its severity class and the first message as its title. Rebuilt only when the line count or the marks change.
function builderYamlGutter(){
 const box=builderYamlEl('builder-yaml-editor'),gutter=builderYamlEl('builder-yaml-gutter');if(!box||!gutter)return;
 const lines=box.value.split('\n').length;
 if(lines!==builderYaml.lines||builderYaml.markSig!==builderYaml.builtSig){
  builderYaml.lines=lines;builderYaml.builtSig=builderYaml.markSig;gutter.replaceChildren();
  for(let n=1;n<=lines;n++){
   const mark=builderYaml.marks.get(n),span=builderYamlMake('span','builder-yaml-line'+(mark?' is-'+mark.severity:''),String(n));
   if(mark)span.setAttribute('title',mark.message);
   gutter.append(span);if(n<lines)gutter.append('\n');
  }
 }
 gutter.scrollTop=box.scrollTop;
}
// The gutter marks of a list (an error beats a warning on the same line); an empty or missing list clears them.
function builderYamlMarks(list){
 const marks=new Map();
 for(const f of Array.isArray(list)?list:[]){if(!(f.line>0))continue;const old=marks.get(f.line);if(!old||(old.severity!=='error'&&f.severity==='error'))marks.set(f.line,{severity:f.severity,message:f.message});}
 builderYaml.marks=marks;builderYaml.markSig=[...marks].map(([line,m])=>line+m.severity[0]+m.message).join('\u0000');
}
function builderYamlSet(text){
 const box=builderYamlEl('builder-yaml-editor');if(box)box.value=text;
 builderYaml.base=text;builderYaml.dirty=false;builderYaml.canvasChanged=false;builderYamlMarks([]);builderYamlGutter();builderYamlButtons();
 builderYamlLater();
}
// Puts the caret on a 1-based line, so the student lands where the refusal points. An Apply refusal selects the line
// (the first key typed then replaces it); the Problems list passes {select:false}: the caret lands on the key, nothing selected.
function builderYamlGoto(line,options){
 const box=builderYamlEl('builder-yaml-editor');if(!box||!(line>0))return;
 const rows=box.value.split('\n'),n=Math.min(line,rows.length);let start=0;for(let i=0;i<n-1;i++)start+=rows[i].length+1;
 if(typeof box.focus==='function')box.focus();
 if(typeof box.setSelectionRange!=='function')return;
 if(options&&options.select===false){const lead=/^\s*(?:- )?/.exec(rows[n-1])[0].length;box.setSelectionRange(start+lead,start+lead);}
 else box.setSelectionRange(start,start+rows[n-1].length);
}
// Every stored state of the editor arrives here (after the page stored it).
function builderYamlHeard(yaml){
 yaml=String(yaml??'');if(yaml===builderYaml.base)return;
 // The text the student just applied coming back: the panel is in step.
 if(yaml===builderYamlText()){builderYaml.base=yaml;builderYaml.dirty=false;builderYaml.canvasChanged=false;builderYamlButtons();return;}
 if(!builderYaml.dirty&&!builderYaml.applying){const was=builderYaml.status;builderYamlSet(yaml);if(was===BUILDER_YAML_TEXT.canvas||was===BUILDER_YAML_TEXT.applied||was===BUILDER_YAML_TEXT.reverted||/^Applied · \d+ errors? remains? /.test(was))builderYamlShow('','');return;}
 builderYaml.canvasChanged=true;builderYamlShow(BUILDER_YAML_TEXT.canvas,'warn');builderYamlButtons();
}
function builderYamlInput(){
 builderYaml.dirty=builderYamlText()!==builderYaml.base;
 // A stale mark never points at a moved line: every keystroke clears them, the next check draws them again.
 builderYamlMarks([]);builderYamlGutter();
 // Typed back to what it was while the canvas moved on: nothing of the student's is left to keep.
 if(!builderYaml.dirty&&builderYaml.canvasChanged&&!builderYaml.applying){builderYamlSet(builderYamlCurrent());builderYamlShow('','');return;}
 if(!builderYaml.applying)builderYamlShow(builderYaml.dirty?(builderYaml.canvasChanged?BUILDER_YAML_TEXT.canvas:BUILDER_YAML_TEXT.edited):'',builderYaml.dirty&&builderYaml.canvasChanged?'warn':'');
 builderYamlButtons();
 if(builderYaml.timer!==null)clearTimeout(builderYaml.timer);
 builderYaml.timer=builderYaml.dirty?setTimeout(builderYamlTick,BUILDER_YAML_DELAY):null;
 // Typed back to the engine's text: nothing is waiting to be validated, but the list still follows the text.
 if(!builderYaml.dirty)builderYamlCheckList();
}
// One timer for both paths (the status line's dirty-only validation and the list), so a burst of keystrokes costs one parse.
function builderYamlLater(){
 if(!builderYaml.open)return;
 if(builderYaml.timer!==null)clearTimeout(builderYaml.timer);
 builderYaml.timer=setTimeout(builderYamlTick,BUILDER_YAML_DELAY);
}
function builderYamlTick(){
 builderYaml.timer=null;
 const wantStatus=builderYaml.dirty&&!builderYaml.applying&&!!builderYaml.editor&&typeof builderYaml.editor.checkYaml==='function';
 if(!wantStatus&&!builderYaml.open)return;
 const analysis=builderYamlAnalyse(builderYamlText());
 const done=builderYamlCheckList(undefined,analysis);
 if(wantStatus)builderYamlValidate(analysis,!!(done&&done.checked));
}
// The adapter's answers for one text: checkYaml's flaw (the parser and shape check) and locateYaml's tree (section 2.1).
function builderYamlAnalyse(text){
 const e=builderYaml.editor,a={flaw:null,tree:null,located:null,limit:null,checkFailed:false};
 if(e&&typeof e.checkYaml==='function'){try{a.flaw=e.checkYaml(text)||null;}catch{a.checkFailed=true;}}
 if(e&&typeof e.locateYaml==='function'){try{a.located=e.locateYaml(text)||null;}catch{a.located=null;}}
 a.tree=a.located&&a.located.tree?a.located.tree:null;
 // locateYaml's own limits (depth, size, time) are not a parse error: they only mean the advisory check did not run.
 if(!a.flaw&&!a.tree&&a.located&&a.located.error&&typeof a.located.error.message==='string')a.limit=a.located.error.message;
 return a;
}
// Parser and shape check only; the engine is not asked until Apply. A checkYaml warning (an endpoint naming an unknown device) is
// written here unless the list check ran on this text: then the list carries it as an error of its own.
function builderYamlValidate(known,listed){
 const e=builderYaml.editor;
 if(!builderYaml.dirty||builderYaml.applying||!e||typeof e.checkYaml!=='function')return null;
 const a=known||builderYamlAnalyse(builderYamlText());
 if(a.checkFailed)return null;
 const flaw=a.flaw,quiet=!flaw||(flaw.severity==='warning'&&!!listed);
 if(quiet)builderYamlShow(builderYaml.canvasChanged?BUILDER_YAML_TEXT.canvas:BUILDER_YAML_TEXT.edited,builderYaml.canvasChanged?'warn':'');
 else builderYamlShow((flaw.line?'Line '+flaw.line+': ':'')+flaw.message,flaw.severity==='warning'?'warn':'error');
 return flaw||null;
}

// --- the Problems list (section 4.1) ------------------------------------------------------------------------
function builderYamlAvailable(){return typeof builderCheck==='function'&&typeof builderCheckSummary==='function'&&typeof builderSchemaChoice==='function';}
function builderYamlChoice(){return builderYamlAvailable()?builderSchemaChoice(builderYaml.vmVersion,typeof BUILDER_SCHEMA_VERSIONS!=='undefined'?BUILDER_SCHEMA_VERSIONS:[]):null;}
function builderYamlSchemaNow(){const s=builderYaml.schemaState;return s&&s.status==='ready'?s.data:null;}
// The release marker of the page's own script tag, so the schema URL carries the same ?v= as the other assets without a second copy of the number.
function builderYamlRelease(){
 if(typeof document==='undefined'||!document||typeof document.querySelector!=='function')return '';
 const tag=document.querySelector('script[src*="lab-builder-check.js"]'),m=tag&&typeof tag.getAttribute==='function'?/\?v=([^"&#\s]+)/.exec(tag.getAttribute('src')||''):null;
 return m?'?v='+m[1]:'';
}
// The one schema loader of the page (the panel and the bar note share it): fetched once per page load and kept; resolves the schema, or null
// when the fetch failed. Nothing waits on it: the schema-free rules run before it arrives.
function builderYamlSchema(){
 const choice=builderYamlChoice();if(!choice||!choice.schemaVersion)return Promise.resolve(null);
 const known=builderYaml.schemaState;
 if(known&&known.version===choice.schemaVersion){if(known.status==='ready')return Promise.resolve(known.data);if(known.promise)return known.promise;return Promise.resolve(null);}
 const state={version:choice.schemaVersion,status:'loading',data:null,promise:null};builderYaml.schemaState=state;
 state.promise=Promise.resolve().then(()=>{
  if(typeof fetch!=='function')throw new Error('fetch');
  return fetch('/static/clab-schema/'+choice.schemaVersion+'.json'+builderYamlRelease());
 }).then(r=>{if(!r||!r.ok)throw new Error('status');return r.json();}).then(data=>{
  if(!data||typeof data!=='object'||typeof data.definitions!=='object')throw new Error('shape');
  if(builderYaml.schemaState===state){state.status='ready';state.data=data;}
  return data;
 }).catch(()=>{if(builderYaml.schemaState===state)state.status='failed';return null;}).then(value=>{
  // The list was drawn without it: draw it again with the settings checked.
  if(builderYaml.schemaState===state)builderYamlCheckList();
  return value;
 });
 return state.promise;
}
function builderYamlSchemaRetry(){builderYaml.schemaState=null;builderYamlSchema();builderYamlCheckList();}
// The page hands the VM's capabilities over when they arrive (and null when they could not be read): the schema choice and the
// severities upgrade on the next validation, no reload.
function builderYamlContext(caps){
 builderYaml.vmVersion=caps&&typeof caps.containerlab==='string'?caps.containerlab:'';
 const choice=builderYamlChoice(),state=builderYaml.schemaState;
 if(state&&choice&&state.version!==choice.schemaVersion)builderYaml.schemaState=null;
 builderYamlCheckList();
}
function builderYamlCheckContext(choice){return {version:builderYaml.vmVersion,schemaVersion:choice?choice.schemaVersion:'',exact:!!(choice&&choice.exact)};}
// The page's bar note: the adapter's tree of a text (null when no editor is attached or it has no locateYaml; it may throw, the page guards it),
// and the findings for a tree with whatever schema has arrived.
function builderYamlLocate(text){const e=builderYaml.editor;if(!e||typeof e.locateYaml!=='function')return null;return e.locateYaml(String(text??''))||null;}
function builderYamlRun(tree){const choice=builderYamlChoice();return builderCheck(tree,builderYamlSchemaNow(),builderYamlCheckContext(choice));}
// The count is rewritten after every typing pause, so it is not a live region; the same sentence is spoken once here after Apply,
// Revert and when the panel opens.
function builderYamlAnnounce(){
 const el=builderYamlEl('builder-yaml-announce');if(!el)return;
 el.textContent='';el.textContent=builderYaml.countText||'';
}
function builderYamlCount(text,warn){
 const tone=warn?'builder-yaml-status is-warn':'';
 if(text===builderYaml.countText&&tone===builderYaml.countTone)return;builderYaml.countText=text;builderYaml.countTone=tone;
 const count=builderYamlEl('builder-yaml-count');if(count){count.textContent=text;count.className=tone;}
}
// Where keyboard focus sits in the list before it is redrawn: the item (by its line and code), or the list itself.
function builderYamlFocusIn(ol){
 const a=typeof document!=='undefined'&&document?document.activeElement:null;if(!a)return null;
 if(a===ol)return {list:true,line:'',code:''};
 const line=typeof a.getAttribute==='function'?a.getAttribute('data-line'):null;
 if(line===null||(typeof ol.contains==='function'&&!ol.contains(a)))return null;
 return {list:false,line,code:a.getAttribute('data-code')||''};
}
function builderYamlRenderList(list){
 const ol=builderYamlEl('builder-yaml-list');if(!ol)return;
 // A redraw destroys the focused button: keep focus on the same item (line and code), or on the list when that item is gone.
 const had=builderYamlFocusIn(ol);let again=null;
 ol.replaceChildren();
 for(const f of list){
  const li=builderYamlMake('li','is-'+f.severity);
  if(f.line>0){
   const b=builderYamlMake('button','builder-yaml-problem');b.setAttribute('type','button');b.setAttribute('data-line',String(f.line));b.setAttribute('data-code',String(f.code||''));
   if(had&&!had.list&&!again&&String(f.line)===had.line&&String(f.code||'')===had.code)again=b;
   b.append(builderYamlMake('span','builder-yaml-sev',f.severity==='error'?'Error':f.severity==='info'?'Note':'Warning'),' Line '+f.line+': '+f.message);li.append(b);
  }else li.append(f.message);
  ol.append(li);
 }
 // A list that scrolls is reachable by keyboard.
 if(ol.scrollHeight>ol.clientHeight)ol.setAttribute('tabindex','0');else if(had&&!again)ol.setAttribute('tabindex','-1');else ol.removeAttribute('tabindex');
 if(had&&typeof (again||ol).focus==='function')(again||ol).focus({preventScroll:true});
}
function builderYamlCaption(text){const p=builderYamlEl('builder-yaml-schema');if(p&&p.textContent!==text)p.textContent=text;}
// Runs the check over the panel's text and draws the list, the gutter marks, the count and aria-invalid; never the status line.
// Active whenever a tree exists. `known` is an analysis already made for the same text. Returns {errors,warnings,checked}, or null
// when the panel is closed or the check script is absent.
function builderYamlCheckList(text,known){
 if(!builderYaml.open||!builderYamlAvailable())return null;
 text=text===undefined?builderYamlText():text;
 const a=known||builderYamlAnalyse(text),choice=builderYamlChoice();
 builderYaml.tree=a.tree;builderYaml.treeText=text;
 const blocking=!!a.flaw&&a.flaw.severity!=='warning';
 let list=[],checked=false;
 if(a.tree){
  if(!builderYaml.schemaState)builderYamlSchema();
  try{list=builderCheck(a.tree,builderYamlSchemaNow(),builderYamlCheckContext(choice));checked=true;}catch{list=[];}
  // The status line shows a blocking error already; the list does not repeat it.
  if(blocking)list=list.filter(f=>f.code!=='shape');
 }
 const state=builderYaml.schemaState,summary=checked?builderCheckSummary(list):{errors:0,warnings:0,text:''};
 let sentence='';
 if(checked)sentence=blocking&&!list.length?BUILDER_YAML_TEXT.notChecked:summary.text+(state&&state.status==='loading'?' '+BUILDER_YAML_TEXT.settingsPending:'');
 else if(blocking)sentence=BUILDER_YAML_TEXT.notChecked;
 else if(a.limit)sentence='Not checked: '+a.limit;
 builderYamlCaption(checked&&builderYamlReady()&&choice?choice.caption:'');
 builderYamlRenderList(list);builderYamlMarks(list);builderYaml.listErrors=summary.errors;
 builderYamlCount(sentence,!checked&&!blocking&&!!a.limit);builderYamlInvalid();builderYamlGutter();
 const failed=builderYamlEl('builder-yaml-schema-failed');if(failed)failed.hidden=!(state&&state.status==='failed'&&checked);
 builderYamlKeyHelpNow();
 return {errors:summary.errors,warnings:summary.warnings,checked};
}
function builderYamlProblemClick(event){
 const b=event&&event.target&&typeof event.target.closest==='function'?event.target.closest('button[data-line]'):null;
 if(b)builderYamlGoto(Number(b.getAttribute('data-line')),{select:false});
}

// --- key help on the caret (section 4.3) --------------------------------------------------------------------
function builderYamlKeyHelpSoon(){
 if(builderYaml.keyTimer!==null)return;
 // selectionchange fires for the whole document: only the panel's own text box matters.
 builderYaml.keyTimer=setTimeout(builderYamlKeyHelpNow,BUILDER_YAML_KEY_DELAY);
}
function builderYamlKeyHelpNow(){
 builderYaml.keyTimer=null;
 const out=builderYamlEl('builder-yaml-keyhelp'),box=builderYamlEl('builder-yaml-editor');if(!out)return;
 const clear=()=>{if(out.textContent!=='')out.replaceChildren();};
 const schema=builderYamlSchemaNow();
 if(!builderYaml.open||!box||!schema||!builderYaml.tree||typeof builderKeyHelp!=='function'){clear();return;}
 const text=box.value,caret=typeof box.selectionStart==='number'?box.selectionStart:0,line=text.slice(0,caret).split('\n').length;
 const row=text.split('\n')[line-1]||'',m=/^\s*(?:- )?([\w.-]+):/.exec(row);
 // The tree can be behind the text between a keystroke and the next validation: help only for the line the tree was made from.
 if(!m||builderYaml.treeText.split('\n')[line-1]!==row){clear();return;}
 let help=null;try{help=builderKeyHelp(builderYaml.tree,schema,line);}catch{help=null;}
 if(!help||help.key!==m[1]){clear();return;}
 out.replaceChildren();
 out.append(builderYamlMake('code','',help.key),help.description?' · '+help.description+' ':' ');
 // Only the schema's containerlab.dev link is offered; the manager is not a link checker for anything else.
 if(typeof help.url==='string'&&/^https:\/\/containerlab\.dev\//.test(help.url)){
  const a=builderYamlMake('a','','More about '+help.key);a.setAttribute('href',help.url);a.setAttribute('target','_blank');a.setAttribute('rel','noopener');out.append(a);
 }
}
// At 900 px and below the caption and the key help sit under a closed disclosure so the text box keeps its height; wider, they are always shown.
function builderYamlLayout(){
 const more=builderYamlEl('builder-yaml-more');if(!more)return;
 more.open=!(typeof matchMedia==='function'&&matchMedia(BUILDER_YAML_NARROW).matches);
}

function builderYamlApply(){
 const e=builderYaml.editor;if(builderYaml.applying||!builderYamlReady())return Promise.resolve(false);
 if(!builderYaml.dirty){builderYamlShow(BUILDER_YAML_TEXT.nothing,'');return Promise.resolve(false);}
 const text=builderYamlText();if(builderYaml.timer!==null){clearTimeout(builderYaml.timer);builderYaml.timer=null;}
 builderYaml.applying=true;builderYamlShow(BUILDER_YAML_TEXT.applying,'');builderYamlButtons();
 return Promise.resolve().then(()=>e.applyYaml(text)).then(()=>{
  builderYaml.applying=false;builderYaml.base=typeof e.getYaml==='function'?String(e.getYaml()??''):text;builderYaml.canvasChanged=false;
  builderYaml.dirty=builderYamlText()!==builderYaml.base;
  // The text is applied whatever the list says (decision 4); it names the errors that remain.
  const found=builderYamlCheckList(),errors=found?found.errors:0;
  if(builderYaml.dirty)builderYamlShow(BUILDER_YAML_TEXT.appliedNewer,'ok');
  else if(errors>0)builderYamlShow('Applied · '+errors+' error'+(errors===1?' remains':'s remain')+' (see Problems)','warn');
  else builderYamlShow(BUILDER_YAML_TEXT.applied,'ok');
  builderYamlGutter();builderYamlButtons();builderYamlAnnounce();
  if(typeof builderYaml.onApplied==='function')builderYaml.onApplied(text);
  return true;
 },err=>{
  // Refused: the text stays for the student to correct; the engine and the map are as they were.
  builderYaml.applying=false;builderYamlShow(err&&err.message?err.message:String(err),'error');builderYamlButtons();
  if(err&&err.line)builderYamlGoto(err.line);
  return false;
 });
}
function builderYamlRevert(){if(builderYaml.applying)return;builderYamlSet(builderYamlCurrent());builderYamlShow(BUILDER_YAML_TEXT.reverted,'');builderYamlCheckList();builderYamlAnnounce();}
function builderYamlKey(event){
 if(event.key==='Enter'&&(event.ctrlKey||event.metaKey)){event.preventDefault();builderYamlApply();}
}
// Escape closes a clean panel only; closing with the button (or the bar's toggle) just hides it and keeps
// the unapplied text and its status for the next opening.
function builderYamlPanelKey(event){
 if(event.key!=='Escape')return;event.preventDefault();if(typeof event.stopPropagation==='function')event.stopPropagation();
 if(builderYaml.dirty||builderYaml.applying)builderYamlShow(BUILDER_YAML_TEXT.closeDirty,'warn');else builderYamlPanelToggle(false);
}
// Returns the new open state (the page mirrors it in its toggle's aria-expanded).
function builderYamlPanelToggle(open){
 const panel=builderYamlEl('builder-yaml-panel');if(!panel)return false;
 const next=open===undefined?!!panel.hidden:!!open;
 if(next&&!builderYaml.dirty&&!builderYaml.applying)builderYamlSet(builderYamlCurrent());
 // Whether focus sits inside the panel is read before it is hidden: a hidden element may already have lost it.
 const active=typeof document!=='undefined'&&document?document.activeElement:null;
 const hadFocus=!next&&!!active&&typeof panel.contains==='function'&&panel.contains(active);
 panel.hidden=!next;builderYaml.open=next;
 if(next){const box=builderYamlEl('builder-yaml-editor');if(box&&typeof box.focus==='function')box.focus();builderYamlCheckList();builderYamlAnnounce();}
 if(typeof builderYaml.onToggle==='function')builderYaml.onToggle(next,hadFocus);
 return next;
}
// options: editor (the adapter's handle, or null until the editor is attached), getDraftYaml (the page's
// newest stored-or-unstored text), onApplied(text), onToggle(open) (every open and close, the panel's own
// close button and Escape included, so the page can mirror it in its layout). Calling it again replaces the editor and its subscription.
function builderYamlPanelInit(options){
 const o=options||{};
 if(typeof builderYaml.unsubscribe==='function')builderYaml.unsubscribe();
 if(builderYaml.timer!==null){clearTimeout(builderYaml.timer);builderYaml.timer=null;}
 Object.assign(builderYaml,{editor:o.editor||null,getDraftYaml:o.getDraftYaml||null,onApplied:o.onApplied||null,onToggle:o.onToggle||null,unsubscribe:null,applying:false,lines:0,builtSig:'\u0000'});
 const box=builderYamlEl('builder-yaml-editor'),panel=builderYamlEl('builder-yaml-panel');
 if(box){box.oninput=builderYamlInput;box.onkeydown=builderYamlKey;box.onscroll=builderYamlGutter;box.onkeyup=builderYamlKeyHelpSoon;box.onclick=builderYamlKeyHelpSoon;}
 if(panel)panel.onkeydown=builderYamlPanelKey;
 for(const [id,fn] of [['builder-yaml-apply',builderYamlApply],['builder-yaml-revert',builderYamlRevert],['builder-yaml-close',()=>builderYamlPanelToggle(false)],['builder-yaml-schema-retry',builderYamlSchemaRetry],['builder-yaml-list',builderYamlProblemClick]]){const b=builderYamlEl(id);if(b)b.onclick=fn;}
 // The caret moves without a key or a click too (touch, drag selection): one document listener for the page's life.
 if(!builderYaml.bound&&typeof document!=='undefined'&&document&&typeof document.addEventListener==='function'){
  builderYaml.bound=true;
  document.addEventListener('selectionchange',()=>{const b=builderYamlEl('builder-yaml-editor');if(b&&document.activeElement===b)builderYamlKeyHelpSoon();});
  if(typeof matchMedia==='function'){const q=matchMedia(BUILDER_YAML_NARROW);if(q&&typeof q.addEventListener==='function')q.addEventListener('change',builderYamlLayout);}
 }
 builderYamlLayout();
 // Unapplied edits survive a re-initialisation (the editor attaching after the panel was opened).
 if(!builderYaml.dirty)builderYamlSet(builderYamlCurrent());else{builderYamlGutter();builderYamlButtons();}
 const e=builderYaml.editor;
 if(e&&typeof e.subscribe==='function')builderYaml.unsubscribe=e.subscribe(builderYamlHeard);
 if(!builderYamlReady())builderYamlShow(BUILDER_YAML_TEXT.notReady,'');else if(builderYaml.status===BUILDER_YAML_TEXT.notReady)builderYamlShow('','');
 builderYamlCheckList();
 return builderYamlPanelState();
}
function builderYamlPanelState(){
 const {open,dirty,applying,canvasChanged,base,status,tone}=builderYaml;
 return {open,dirty,applying,canvasChanged,base,status,tone,text:builderYamlText(),ready:builderYamlReady(),count:builderYaml.countText};
}
