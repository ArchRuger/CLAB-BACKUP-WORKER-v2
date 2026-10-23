'use strict';
// Copy to the clipboard, for every page that shows a value worth copying (docs/parity-campaign/C02-DESIGN.md section 2).
// Loads in Node: navigator and document are touched only inside functions, except the one guarded click delegation at the end.
const COPY_FAILED='Could not copy. The value is selected: press Ctrl+C.';
const copyFlips=new WeakMap();
function copyEscape(value){return typeof esc==='function'?esc(value):String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
// Select the text of the element a Copy button names (never the button itself), so Ctrl+C is one keystroke away.
function copySelectTarget(source){
 try{
  const id=source&&source.dataset&&source.dataset.copyTarget;if(!id)return;
  const target=document.getElementById(id);if(!target)return;
  if(typeof target.select==='function'){target.focus();target.select();return;}
  const range=document.createRange();range.selectNodeContents(target);const selection=window.getSelection();selection.removeAllRanges();selection.addRange(range);
 }catch{}
}
// Returns true only when the text was really copied; never throws.
async function copyText(text,source){
 const value=String(text??'');
 try{if(navigator.clipboard&&navigator.clipboard.writeText){await navigator.clipboard.writeText(value);return true;}}catch{}
 let sink=null;
 // The textarea takes focus to copy; the page gets it back afterwards, so a keyboard user stays where they were.
 const before=typeof document!=='undefined'&&document?document.activeElement:null;
 try{
  // A modal dialog makes the rest of the page inert: a textarea outside it never takes focus, and execCommand would still say true.
  const host=(source&&source.closest&&source.closest('dialog[open]'))||document.body;
  sink=document.createElement('textarea');sink.className='copy-sink';sink.setAttribute('readonly','');sink.setAttribute('aria-hidden','true');sink.value=value;
  host.appendChild(sink);sink.focus({preventScroll:true});sink.select();
  const selected=document.activeElement===sink&&sink.selectionStart===0&&sink.selectionEnd===value.length;
  const done=selected&&document.execCommand('copy')===true;
  if(done)return true;
 }catch{}
 finally{
  try{if(sink&&sink.parentNode)sink.parentNode.removeChild(sink);else if(sink&&typeof sink.remove==='function')sink.remove();}catch{}
  try{if(sink&&before&&before.isConnected!==false&&typeof before.focus==='function')before.focus({preventScroll:true});}catch{}
 }
 copySelectTarget(source);
 return false;
}
// The Copied flip and the announcement: a status span beside the button inside a dialog, #tools-status on the terminal page, else the toast.
function copyFeedback(button,ok){
 if(!button)return;
 const sentence=ok?'Copied':COPY_FAILED;
 const dialog=button.closest&&button.closest('dialog[open]');
 const beside=button.nextElementSibling&&button.nextElementSibling.classList&&button.nextElementSibling.classList.contains('copy-status')?button.nextElementSibling:null;
 let shown=false;
 if(dialog&&beside){beside.textContent=sentence;shown=true;if(!ok){const error=dialog.querySelector('.form-error');if(error)error.textContent=sentence;}}
 if(!shown&&typeof document!=='undefined'){const tools=document.getElementById&&document.getElementById('tools-status');if(tools){tools.textContent=sentence;tools.title=sentence;shown=true;}}
 if(!shown&&!dialog&&typeof notify==='function'){notify(sentence);shown=true;}
 if(!shown&&beside){beside.textContent=sentence;}
 if(!ok)return;
 let flip=copyFlips.get(button);
 if(flip)clearTimeout(flip.timer);
 else{flip={text:button.dataset.label||button.textContent,label:button.getAttribute('aria-label')};copyFlips.set(button,flip);}
 button.textContent='Copied';button.setAttribute('aria-label','Copied');
 flip.timer=setTimeout(()=>{copyFlips.delete(button);button.textContent=flip.text;if(flip.label===null||flip.label===undefined)button.removeAttribute('aria-label');else button.setAttribute('aria-label',flip.label);if(beside&&beside.textContent==='Copied')beside.textContent='';},2000);
}
// visible is the button's own text (default Copy); two buttons in one row need different words.
function copyButton(value,what,targetId,visible){
 const text=String(value??'');if(!text)return '';
 const shown=copyEscape(visible||'Copy');
 return `<button type="button" class="button ghost small copy-button" data-copy="${copyEscape(text)}" data-copy-target="${copyEscape(targetId||'')}" data-label="${shown}" aria-label="Copy ${copyEscape(what)}">${shown}</button><span class="copy-status" role="status"></span>`;
}
if(typeof document!=='undefined'&&document&&typeof document.addEventListener==='function'){
 document.addEventListener('click',event=>{
  const button=event.target&&event.target.closest?event.target.closest('button[data-copy]'):null;
  if(!button||button.disabled)return;
  copyText(button.dataset.copy,button).then(ok=>copyFeedback(button,ok));
 });
}
