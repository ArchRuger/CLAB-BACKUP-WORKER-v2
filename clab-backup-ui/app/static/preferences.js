'use strict';
// The Keyboard shortcuts dialog (static markup, opened here) and the Browser preferences dialog (docs/parity-campaign/C09-DESIGN.md
// sections 3 and 5). This script touches no browser storage and registers no document or window listener: the storage, the family
// table and the media queries live in shell.js (preferenceInventory, resetPreferences, mediaMatches, terminalFontPreference,
// setTerminalFontPreference); the dialogs' buttons are wired on their own elements. It sends nothing to the manager.
// The shell.js helpers are called behind typeof guards; the PREFS_FALLBACK_* block below stands in until shell.js has them and
// is deleted with the guards once it does.

// Every keydown listener of the page scripts that is deliberately not a row of the shortcuts dialog, with its reason (section 3).
// The reverse pin in tests/test_shell_ui.js requires each keydown site to be a data-source of a row in index.html or to be listed here.
const SHORTCUT_EXCLUSIONS=[
 {source:'app.js:547',reason:'Previous and Next device in the device panel are buttons without a key.'},
 {source:'shell.js:190',reason:'The lab switcher is a details element: Escape closing it is the dialog’s first sentence.'},
 {source:'shell.js:269',reason:'The Escape handler itself is the dialog’s first sentence.'},
 {source:'shell.js:159',reason:'The Escape handler of the Save chip and Load panels is the dialog’s first sentence.'},
 {source:'topology.js:111',reason:'The Escape handler of the map and its device menu is the dialog’s first sentence.'},
 {source:'lab-builder-page.js:323',reason:'Enter in the new-lab name field submits a form field: a browser default.'},
 {source:'save-drawers.js:1020',reason:'The save drawer’s keydown delegate carries the folder chooser rows and Enter on a form control.'},
 {source:'save-header.js:667',reason:'The Save chip panel’s keydown delegate carries the folder chooser rows and Enter on a form control.'}];

const PREFS_FONT_SIZES=[11,12,13,14,15,16,17,18],PREFS_FONT_DEFAULT=14;
const PREFS_STATUS_KEPT='This browser does not let the page keep this setting.';
const PREFS_BLOCKED_BODY='This browser does not let the page read or keep its storage (a private window, or site data blocked). Nothing is remembered between visits, so there is nothing to show or reset.';
const PREFS_BLOCKED_RESET='Not available: storage is blocked in this browser.';
const PREFS_FULL='This browser is not letting the page store anything new (storage full or read-only).';
const PREFS_NOT_STORED='The open folders of the save chooser and the Home filter are kept only while this page is open.';
const PREFS_APPEARANCE='Appearance: light. The terminal page is dark by design; there is no dark mode setting.';

// --- stand-ins for the shell.js helpers (removed once shell.js carries them) -------------------------------------------------
const PREFS_STORE_LOCAL='local'+'Storage',PREFS_STORE_SESSION='session'+'Storage';
const PREFS_FALLBACK_EDITOR=['react-topoviewer-grid-line-width','react-topoviewer-grid-style','contextPanelSide','mui-mode','mui-color-scheme-light','mui-color-scheme-dark'];
const PREFS_FALLBACK_FAMILIES=[
 {kind:PREFS_STORE_LOCAL,match:k=>k==='clab.terminal.fontSize',id:'terminal-font',reset:true},
 {kind:PREFS_STORE_LOCAL,match:k=>k.startsWith('clab.opened.'),id:'opened',reset:true},
 {kind:PREFS_STORE_LOCAL,match:k=>k.startsWith('clab.dismissed.'),id:'dismissed',reset:true},
 {kind:PREFS_STORE_LOCAL,match:k=>k.startsWith('clab.design.draft.'),id:'design-drafts',reset:false},
 {kind:PREFS_STORE_LOCAL,match:k=>k.startsWith('clab-builder:draft:'),id:'builder-drafts',reset:false},
 {kind:PREFS_STORE_LOCAL,match:k=>k==='clab-builder:templates'||k==='clab-builder:templates-version',id:'builder-templates',reset:false},
 {kind:PREFS_STORE_LOCAL,match:k=>PREFS_FALLBACK_EDITOR.includes(k),id:'editor-view',reset:true},
 {kind:PREFS_STORE_LOCAL,match:k=>k.startsWith('clab.capture.'),id:'capture',reset:true},
 {kind:PREFS_STORE_SESSION,match:k=>k==='clab.homeTab',id:'home-tab',reset:true},
 {kind:PREFS_STORE_SESSION,match:k=>k.startsWith('clab.notice.'),id:'notices',reset:true},
 {kind:PREFS_STORE_SESSION,match:k=>k==='activeLab',id:'active-lab',reset:false},
 {kind:PREFS_STORE_SESSION,match:k=>k.startsWith('clab.request.'),id:'requests',reset:false},
 {kind:PREFS_STORE_SESSION,match:k=>k.startsWith('git-save-request:'),id:'save-requests',reset:false},
 {kind:PREFS_STORE_SESSION,match:k=>k==='op-return',id:'op-return',reset:false}];
function prefsFallbackStore(kind){try{return globalThis[kind]||null;}catch{return null;}}
function prefsFallbackKeys(kind){try{const s=prefsFallbackStore(kind),out=[];for(let i=0;i<s.length;i++){const k=s.key(i);if(k!==null)out.push(k);}return out;}catch{return null;}}
function prefsFallbackInventory(){
 const local=prefsFallbackKeys(PREFS_STORE_LOCAL),session=prefsFallbackKeys(PREFS_STORE_SESSION);
 let writable=false;
 try{const s=prefsFallbackStore(PREFS_STORE_LOCAL);s.setItem('clab.probe','1');s.removeItem('clab.probe');writable=true;}catch{/* full or read-only */}
 const lists={[PREFS_STORE_LOCAL]:local||[],[PREFS_STORE_SESSION]:session||[]};
 const families=PREFS_FALLBACK_FAMILIES.map(f=>{const keys=lists[f.kind].filter(f.match);return {id:f.id,kind:f.kind,reset:f.reset,count:keys.length,keys};});
 return {blocked:local===null,writable,families};
}
function prefsFallbackReset(){
 const inv=prefsFallbackInventory();if(inv.blocked)return {cleared:0,blocked:true};
 let cleared=0;
 for(const f of inv.families){if(!f.reset)continue;for(const k of f.keys){try{prefsFallbackStore(f.kind).removeItem(k);cleared++;}catch{/* kept */}}}
 return {cleared,blocked:false};
}
function prefsFallbackFont(){try{const v=Number(prefsFallbackStore(PREFS_STORE_LOCAL).getItem('clab.terminal.fontSize'));return PREFS_FONT_SIZES.includes(v)?v:PREFS_FONT_DEFAULT;}catch{return PREFS_FONT_DEFAULT;}}
function prefsFallbackSetFont(value){const v=Number(value);if(!PREFS_FONT_SIZES.includes(v))return false;try{prefsFallbackStore(PREFS_STORE_LOCAL).setItem('clab.terminal.fontSize',String(v));return true;}catch{return false;}}
function prefsFallbackMedia(query){try{return !!(typeof matchMedia==='function'&&matchMedia(query).matches);}catch{return false;}}

function prefsInventory(){return typeof preferenceInventory==='function'?preferenceInventory():prefsFallbackInventory();}
function prefsDoReset(){return typeof resetPreferences==='function'?resetPreferences():prefsFallbackReset();}
function prefsFont(){return typeof terminalFontPreference==='function'?terminalFontPreference():prefsFallbackFont();}
function prefsSetFont(value){return typeof setTerminalFontPreference==='function'?setTerminalFontPreference(value):prefsFallbackSetFont(value);}
function prefsMedia(query){return typeof mediaMatches==='function'?mediaMatches(query):prefsFallbackMedia(query);}
function prefsDisplay(){return {motion:prefsMedia('(prefers-reduced-motion: reduce)'),contrast:prefsMedia('(prefers-contrast: more)'),forced:prefsMedia('(forced-colors: active)')};}
// The Home list tab as a word the markup knows ('recent', 'all' or ''): the raw stored value is never interpolated.
function prefsHomeWord(inventory){
 const f=prefsFamily(inventory,'home-tab');if(!f.count)return '';
 const tab=typeof homeTab==='function'?homeTab():'recent';
 return tab==='all'?'all':'recent';
}

// --- pure markup --------------------------------------------------------------------------------------------------------------
function prefsFamily(inventory,id){const f=((inventory&&inventory.families)||[]).find(x=>x.id===id);return f||{id,count:0,keys:[]};}
function prefsCount(inventory,id){return Number(prefsFamily(inventory,id).count)||0;}
function prefsPlural(n,one,many){return n===1?`1 ${one}`:`${n} ${many||one+'s'}`;}
function prefsJoin(parts){return parts.length<2?parts.join(''):parts.slice(0,-1).join(', ')+' and '+parts[parts.length-1];}
function prefsRow(label,value){return `<dt>${label}</dt><dd>${value}</dd>`;}
function prefsOnOff(on){return on?'on':'off';}
// What Reset would do, with the counts of the inventory; a family with nothing stored is left out.
function prefsConfirmSentence(inventory){
 const c=id=>prefsCount(inventory,id);
 const here=[];
 if(c('terminal-font'))here.push('the terminal text size');
 if(c('opened'))here.push(`the Last opened times of ${prefsPlural(c('opened'),'lab')}`);
 if(c('editor-view'))here.push('the editor view settings');
 if(c('capture'))here.push('the remembered capture choices');
 if(c('dismissed'))here.push(`which warnings about failed operations you closed (${prefsPlural(c('dismissed'),'warning')}): those warnings show again and their labs read Needs attention until you close them again`);
 const tab=[];
 if(c('home-tab'))tab.push('the Home list tab');
 if(c('notices'))tab.push('the closed notices');
 if(!here.length&&!tab.length)return 'Nothing is stored for the manager in this browser.';
 const parts=[];
 if(here.length)parts.push(`In this browser this forgets ${prefsJoin(here)}.`);
 if(tab.length)parts.push(`In this tab only, it forgets ${prefsJoin(tab)}; other open tabs keep theirs.`);
 parts.push('Drafts, templates and Try again requests are kept.');
 return parts.join(' ');
}
// inventory: shell.js preferenceInventory(); display: {motion, contrast, forced}; font: the effective terminal size;
// homeWord: 'recent' | 'all' | '' (prefsHomeWord). Only the font number and that word are ever interpolated.
function prefsMarkup(inventory,display,font,homeWord){
 const inv=inventory||{},d=display||{},blocked=!!inv.blocked,writable=inv.writable!==false,c=id=>prefsCount(inv,id);
 const size=PREFS_FONT_SIZES.includes(Number(font))?Number(font):PREFS_FONT_DEFAULT;
 const displayHtml=`<section><h3>Display settings the manager follows</h3><p class="caption">From your system or browser; the manager stores nothing for them.</p><dl class="kv">${prefsRow('Reduced motion',prefsOnOff(d.motion))}${prefsRow('More contrast',prefsOnOff(d.contrast))}${prefsRow('Forced colours',prefsOnOff(d.forced))}</dl><p class="caption">${PREFS_APPEARANCE}</p></section>`;
 const resetBtn=`<button type="button" class="button secondary" id="prefs-reset"${blocked?` disabled title="${esc(PREFS_BLOCKED_RESET)}"`:''}>Reset browser preferences…</button>`;
 const resetHtml=`<section><div class="dialog-actions">${blocked?`<span class="caption">${PREFS_BLOCKED_RESET}</span>`:''}${resetBtn}</div>`
  +(blocked?'':`<div id="prefs-reset-confirm" class="banner warn" role="group" aria-label="Confirm reset" hidden><p>${esc(prefsConfirmSentence(inv))}</p><div class="dialog-actions"><button type="button" class="button secondary" id="prefs-reset-keep">Keep</button><button type="button" class="button danger" id="prefs-reset-go">Reset</button></div></div>`)+'</section>';
 if(blocked)return `<p>${PREFS_BLOCKED_BODY}</p>${displayHtml}${resetHtml}`;
 const options=PREFS_FONT_SIZES.map(n=>`<option value="${n}"${n===size?' selected':''}>${n} px${n===PREFS_FONT_DEFAULT?' (default)':''}</option>`).join('');
 const terminal=`<section><h3>Terminal</h3><div class="field"><label for="pref-terminal-font">Terminal text size</label><select id="pref-terminal-font"${writable?'':' disabled'}>${options}</select></div>${writable?'':`<p class="caption">${PREFS_FULL}</p>`}</section>`;
 const capKeys=(prefsFamily(inv,'capture').keys||[]).filter(k=>k!=='clab.capture.openas').length;
 const capture=c('capture')?(capKeys?`for ${prefsPlural(capKeys,'device or link','devices and links')}`:'the Open as choice'):'none';
 const here=`<section><h3>Remembered in this browser</h3><dl class="kv">`
  +prefsRow('Terminal text size',c('terminal-font')?`${esc(String(size))} px`:`default (${PREFS_FONT_DEFAULT} px)`)
  +prefsRow('Last opened times',c('opened')?`for ${prefsPlural(c('opened'),'lab')}`:'none')
  +prefsRow('Closed warnings about failed operations',String(c('dismissed')))
  +prefsRow('Editor view',c('editor-view')?`${prefsPlural(c('editor-view'),'setting')} (grid style, grid line width, panel side, colour mode, in the lab builder and Edit map)`:'none')
  +prefsRow('Remembered capture choices',capture)
  +`</dl><h4>Kept by Reset</h4><dl class="kv">`
  +prefsRow('Network design drafts',c('design-drafts')?`${c('design-drafts')} · discard them on the Network design card`:'none')
  +prefsRow('Lab builder drafts',c('builder-drafts')?`${c('builder-drafts')} · Drafts… in the lab builder`:'none')
  +prefsRow('Lab builder templates',c('builder-templates')?'yes':'none')
  +'</dl></section>';
 const word=homeWord==='all'?'All labs':homeWord==='recent'?'Recent labs':'default';
 const tab=`<section><h3>Remembered in this tab</h3><dl class="kv">`
  +prefsRow('Home list tab',esc(word))
  +prefsRow('Closed notices',String(c('notices')))
  +`</dl><h4>Kept by Reset</h4><dl class="kv">`
  +prefsRow('Try again requests',String(c('requests')))
  +prefsRow('A save being sent',String(c('save-requests')))
  +prefsRow('Return to the lab builder',c('op-return')?'yes':'no')
  +prefsRow('The lab that was open',c('active-lab')?'yes':'no')
  +'</dl></section>';
 return terminal+here+tab+`<section><h3>Not stored</h3><p class="caption">${PREFS_NOT_STORED}</p></section>`+displayHtml+resetHtml;
}

// --- behaviour ----------------------------------------------------------------------------------------------------------------
function prefsStatus(text){const el=$('prefs-status');if(el)el.textContent=text;}
function prefsFocus(id){const el=$(id);if(el&&typeof el.focus==='function')el.focus();}
function prefsRender(){
 const body=$('preferences-body');if(!body)return;
 const inventory=prefsInventory();
 body.innerHTML=prefsMarkup(inventory,prefsDisplay(),prefsFont(),prefsHomeWord(inventory));
 const select=$('pref-terminal-font');
 if(select)select.onchange=()=>{
  const v=Number(select.value);
  if(prefsSetFont(v))prefsStatus(`Terminal text size ${v} px. Applies to terminals opened from now on; open terminals keep theirs.`);
  else{select.value=String(prefsFont());prefsStatus(PREFS_STATUS_KEPT);}
 };
 const open=$('prefs-reset'),confirm=$('prefs-reset-confirm'),keep=$('prefs-reset-keep'),go=$('prefs-reset-go');
 if(open&&confirm)open.onclick=()=>{confirm.hidden=false;prefsFocus('prefs-reset-keep');};
 if(keep&&confirm)keep.onclick=()=>{confirm.hidden=true;prefsFocus('prefs-reset');};
 if(go)go.onclick=prefsReset;
}
// The only caller of resetPreferences: the Reset button of the confirm row.
function prefsReset(){
 const result=prefsDoReset()||{cleared:0};
 prefsRender();prefsFocus('prefs-reset');
 if(result.blocked){prefsStatus(PREFS_BLOCKED_RESET);return result;}
 prefsStatus(`Browser preferences reset: ${prefsPlural(Number(result.cleared)||0,'item')} cleared. Terminals opened from now on use the default text size.`);
 return result;
}
function prefsOpen(){
 prefsStatus('');   // a sentence from the last visit must not greet the next one
 prefsRender();
 const dialog=$('preferences-dialog');if(dialog&&!dialog.open&&typeof dialog.showModal==='function')dialog.showModal();
}
function shortcutsOpen(){const dialog=$('shortcuts-dialog');if(dialog&&!dialog.open&&typeof dialog.showModal==='function')dialog.showModal();}
if(typeof $==='function'){
 const shortcuts=$('manager-shortcuts'),preferences=$('manager-preferences');
 if(shortcuts)shortcuts.onclick=shortcutsOpen;
 if(preferences)preferences.onclick=prefsOpen;
}
