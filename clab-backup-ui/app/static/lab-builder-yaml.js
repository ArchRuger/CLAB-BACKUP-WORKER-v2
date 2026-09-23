'use strict';
// The lab builder's editable YAML panel (requirement C4). The text drives the same editing engine as the
// canvas through the adapter's handle (lab-builder/src/main.tsx: applyYaml, getYaml, checkYaml, subscribe):
// there is no second topology model here. Apply replaces the whole topology as one engine step, so the
// editor's own Undo takes it back; a refused text stays in the panel and the graph is untouched.
// Visual edits refresh the text only while the student has no unapplied edits of their own; otherwise the
// panel says the canvas changed and Revert loads it. Nothing here reads the YAML: syntax and shape checks
// are the adapter's (the bundled parser), so this file needs no library and loads in Node for its tests.
const BUILDER_YAML_DELAY=400;
const BUILDER_YAML_TEXT={edited:'Edited · not applied',applying:'Applying…',applied:'Applied',appliedNewer:'Applied · newer edits not applied',canvas:'Canvas changed · Revert to load it',reverted:'Reverted to the editor’s topology',nothing:'Nothing to apply',closeDirty:'Apply or Revert your edits before closing with Escape.',notReady:'The editor is not ready yet: the text is read-only for now.'};
const builderYaml={open:false,dirty:false,applying:false,canvasChanged:false,base:'',status:'',tone:'',editor:null,getDraftYaml:null,onApplied:null,onToggle:null,unsubscribe:null,timer:null,lines:0};
// A line-number gutter scrolled with the text: wrap="off" keeps one text line per gutter line, so the numbers
// stay right as long as both share the font and line height (lab-builder.css). It is aria-hidden: the
// diagnostics line names the line in words, which is what a screen reader needs.
function builderYamlPanelMarkup(){
 return `<aside id="builder-yaml-panel" class="builder-yaml-panel" hidden aria-labelledby="builder-yaml-title">`
  +`<div class="builder-yaml-head"><h2 id="builder-yaml-title">Topology YAML</h2>`
  +`<button type="button" class="button primary" id="builder-yaml-apply" title="Apply (Ctrl+Enter)" aria-keyshortcuts="Control+Enter" disabled>Apply</button>`
  +`<button type="button" class="button secondary" id="builder-yaml-revert" disabled>Revert</button>`
  +`<button type="button" class="icon-button" id="builder-yaml-close" aria-label="Close the YAML panel">×</button></div>`
  +`<p class="form-help builder-yaml-help" id="builder-yaml-help">Edit the topology as text, then Apply (Ctrl+Enter). The map follows, and the editor’s Undo takes an apply back.</p>`
  +`<div class="builder-yaml-body"><pre class="builder-yaml-gutter" id="builder-yaml-gutter" aria-hidden="true">1</pre>`
  +`<textarea id="builder-yaml-editor" class="builder-yaml-editor" spellcheck="false" wrap="off" autocapitalize="off" autocomplete="off" aria-label="Topology YAML" aria-describedby="builder-yaml-status builder-yaml-help"></textarea></div>`
  +`<p id="builder-yaml-status" class="builder-yaml-status" role="status" aria-live="polite"></p></aside>`;
}
function builderYamlEl(id){return typeof document==='undefined'?null:document.getElementById(id);}
function builderYamlReady(){return !!(builderYaml.editor&&typeof builderYaml.editor.applyYaml==='function');}
// The engine's text as of its last settled operation; before the editor is attached, the stored draft.
function builderYamlCurrent(){const e=builderYaml.editor;if(e&&typeof e.getYaml==='function')return String(e.getYaml()??'');return builderYaml.getDraftYaml?String(builderYaml.getDraftYaml()??''):'';}
function builderYamlText(){const box=builderYamlEl('builder-yaml-editor');return box?box.value:builderYaml.base;}
function builderYamlShow(text,tone){
 builderYaml.status=text||'';builderYaml.tone=tone||'';
 const line=builderYamlEl('builder-yaml-status');if(line){line.textContent=builderYaml.status;line.className='builder-yaml-status'+(builderYaml.tone?' is-'+builderYaml.tone:'');}
 const box=builderYamlEl('builder-yaml-editor');if(box)box.setAttribute('aria-invalid',builderYaml.tone==='error'?'true':'false');
}
function builderYamlButtons(){
 const apply=builderYamlEl('builder-yaml-apply'),revert=builderYamlEl('builder-yaml-revert'),box=builderYamlEl('builder-yaml-editor');
 if(apply)apply.disabled=!builderYamlReady()||builderYaml.applying||!builderYaml.dirty;
 if(revert)revert.disabled=builderYaml.applying||!(builderYaml.dirty||builderYaml.canvasChanged);
 if(box)box.readOnly=!builderYamlReady();
}
function builderYamlGutter(){
 const box=builderYamlEl('builder-yaml-editor'),gutter=builderYamlEl('builder-yaml-gutter');if(!box||!gutter)return;
 const lines=box.value.split('\n').length;
 if(lines!==builderYaml.lines){builderYaml.lines=lines;gutter.textContent=Array.from({length:lines},(_,i)=>String(i+1)).join('\n');}
 gutter.scrollTop=box.scrollTop;
}
function builderYamlSet(text){
 const box=builderYamlEl('builder-yaml-editor');if(box)box.value=text;
 builderYaml.base=text;builderYaml.dirty=false;builderYaml.canvasChanged=false;builderYamlGutter();builderYamlButtons();
}
// Puts the caret on a 1-based line, so the student lands where the refusal points.
function builderYamlGoto(line){
 const box=builderYamlEl('builder-yaml-editor');if(!box||!(line>0))return;
 const rows=box.value.split('\n'),n=Math.min(line,rows.length);let start=0;for(let i=0;i<n-1;i++)start+=rows[i].length+1;
 if(typeof box.focus==='function')box.focus();if(typeof box.setSelectionRange==='function')box.setSelectionRange(start,start+rows[n-1].length);
}
// Every stored state of the editor arrives here (after the page stored it).
function builderYamlHeard(yaml){
 yaml=String(yaml??'');if(yaml===builderYaml.base)return;
 // The text the student just applied coming back: the panel is in step.
 if(yaml===builderYamlText()){builderYaml.base=yaml;builderYaml.dirty=false;builderYaml.canvasChanged=false;builderYamlButtons();return;}
 if(!builderYaml.dirty&&!builderYaml.applying){const was=builderYaml.status;builderYamlSet(yaml);if(was===BUILDER_YAML_TEXT.canvas||was===BUILDER_YAML_TEXT.applied||was===BUILDER_YAML_TEXT.reverted)builderYamlShow('','');return;}
 builderYaml.canvasChanged=true;builderYamlShow(BUILDER_YAML_TEXT.canvas,'warn');builderYamlButtons();
}
function builderYamlInput(){
 builderYaml.dirty=builderYamlText()!==builderYaml.base;builderYamlGutter();
 // Typed back to what it was while the canvas moved on: nothing of the student's is left to keep.
 if(!builderYaml.dirty&&builderYaml.canvasChanged&&!builderYaml.applying){builderYamlSet(builderYamlCurrent());builderYamlShow('','');return;}
 if(!builderYaml.applying)builderYamlShow(builderYaml.dirty?(builderYaml.canvasChanged?BUILDER_YAML_TEXT.canvas:BUILDER_YAML_TEXT.edited):'',builderYaml.dirty&&builderYaml.canvasChanged?'warn':'');
 builderYamlButtons();
 if(builderYaml.timer!==null)clearTimeout(builderYaml.timer);
 builderYaml.timer=builderYaml.dirty?setTimeout(builderYamlValidate,BUILDER_YAML_DELAY):null;
}
// Parser and shape check only; the engine is not asked until Apply.
function builderYamlValidate(){
 builderYaml.timer=null;const e=builderYaml.editor;
 if(!builderYaml.dirty||builderYaml.applying||!e||typeof e.checkYaml!=='function')return null;
 let flaw;try{flaw=e.checkYaml(builderYamlText());}catch{return null;}
 if(!flaw)builderYamlShow(builderYaml.canvasChanged?BUILDER_YAML_TEXT.canvas:BUILDER_YAML_TEXT.edited,builderYaml.canvasChanged?'warn':'');
 else builderYamlShow((flaw.line?'Line '+flaw.line+': ':'')+flaw.message,flaw.severity==='warning'?'warn':'error');
 return flaw||null;
}
function builderYamlApply(){
 const e=builderYaml.editor;if(builderYaml.applying||!builderYamlReady())return Promise.resolve(false);
 if(!builderYaml.dirty){builderYamlShow(BUILDER_YAML_TEXT.nothing,'');return Promise.resolve(false);}
 const text=builderYamlText();if(builderYaml.timer!==null){clearTimeout(builderYaml.timer);builderYaml.timer=null;}
 builderYaml.applying=true;builderYamlShow(BUILDER_YAML_TEXT.applying,'');builderYamlButtons();
 return Promise.resolve().then(()=>e.applyYaml(text)).then(()=>{
  builderYaml.applying=false;builderYaml.base=typeof e.getYaml==='function'?String(e.getYaml()??''):text;builderYaml.canvasChanged=false;
  builderYaml.dirty=builderYamlText()!==builderYaml.base;
  builderYamlShow(builderYaml.dirty?BUILDER_YAML_TEXT.appliedNewer:BUILDER_YAML_TEXT.applied,'ok');builderYamlGutter();builderYamlButtons();
  if(typeof builderYaml.onApplied==='function')builderYaml.onApplied(text);
  return true;
 },err=>{
  // Refused: the text stays for the student to correct; the engine and the map are as they were.
  builderYaml.applying=false;builderYamlShow(err&&err.message?err.message:String(err),'error');builderYamlButtons();
  if(err&&err.line)builderYamlGoto(err.line);
  return false;
 });
}
function builderYamlRevert(){if(builderYaml.applying)return;builderYamlSet(builderYamlCurrent());builderYamlShow(BUILDER_YAML_TEXT.reverted,'');}
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
 panel.hidden=!next;builderYaml.open=next;
 if(next){const box=builderYamlEl('builder-yaml-editor');if(box&&typeof box.focus==='function')box.focus();}
 if(typeof builderYaml.onToggle==='function')builderYaml.onToggle(next);
 return next;
}
// options: editor (the adapter's handle, or null until the editor is attached), getDraftYaml (the page's
// newest stored-or-unstored text), onApplied(text), onToggle(open) (every open and close, the panel's own
// close button and Escape included, so the page can mirror it in its layout). Calling it again replaces the editor and its subscription.
function builderYamlPanelInit(options){
 const o=options||{};
 if(typeof builderYaml.unsubscribe==='function')builderYaml.unsubscribe();
 if(builderYaml.timer!==null){clearTimeout(builderYaml.timer);builderYaml.timer=null;}
 Object.assign(builderYaml,{editor:o.editor||null,getDraftYaml:o.getDraftYaml||null,onApplied:o.onApplied||null,onToggle:o.onToggle||null,unsubscribe:null,applying:false,lines:0});
 const box=builderYamlEl('builder-yaml-editor'),panel=builderYamlEl('builder-yaml-panel');
 if(box){box.oninput=builderYamlInput;box.onkeydown=builderYamlKey;box.onscroll=builderYamlGutter;}
 if(panel)panel.onkeydown=builderYamlPanelKey;
 for(const [id,fn] of [['builder-yaml-apply',builderYamlApply],['builder-yaml-revert',builderYamlRevert],['builder-yaml-close',()=>builderYamlPanelToggle(false)]]){const b=builderYamlEl(id);if(b)b.onclick=fn;}
 // Unapplied edits survive a re-initialisation (the editor attaching after the panel was opened).
 if(!builderYaml.dirty)builderYamlSet(builderYamlCurrent());else{builderYamlGutter();builderYamlButtons();}
 const e=builderYaml.editor;
 if(e&&typeof e.subscribe==='function')builderYaml.unsubscribe=e.subscribe(builderYamlHeard);
 if(!builderYamlReady())builderYamlShow(BUILDER_YAML_TEXT.notReady,'');else if(builderYaml.status===BUILDER_YAML_TEXT.notReady)builderYamlShow('','');
 return builderYamlPanelState();
}
function builderYamlPanelState(){
 const {open,dirty,applying,canvasChanged,base,status,tone}=builderYaml;
 return {open,dirty,applying,canvasChanged,base,status,tone,text:builderYamlText(),ready:builderYamlReady()};
}
