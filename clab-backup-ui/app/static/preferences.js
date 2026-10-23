'use strict';
// The Keyboard shortcuts dialog (static markup, opened here) and the Browser preferences dialog (docs/parity-campaign/C09-DESIGN.md
// sections 3 and 5). This script touches no browser storage and registers no document or window listener: the storage, the family
// table and the media queries live in shell.js (preferenceInventory, resetPreferences, mediaMatches, terminalFontPreference,
// setTerminalFontPreference); the dialogs' buttons are wired on their own elements. It sends nothing to the manager.

// Every keydown listener of the page scripts that is deliberately not a row of the shortcuts dialog, with its reason (section 3).
// The reverse pin in tests/test_shell_ui.js requires each keydown site to be a data-source of a row in index.html or to be listed here,
// and each cited line (row or exclusion) to be a keydown site, so a stale cite fails.
const SHORTCUT_EXCLUSIONS=[
 {source:'home.js:124',reason:'Escape in Find a lab only cancels the browser’s own clearing of a search field: the term is kept, Clear empties it.'},
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

function prefsDisplay(){return {motion:mediaMatches('(prefers-reduced-motion: reduce)'),contrast:mediaMatches('(prefers-contrast: more)'),forced:mediaMatches('(forced-colors: active)')};}
// The Home list tab as a word the markup knows ('recent', 'all' or ''): the raw stored value is never interpolated.
function prefsHomeWord(inventory){
 const f=prefsFamily(inventory,'home-tab');if(!f.count)return '';
 const tab=homeTab();
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
// The short line above the buttons: only the totals; the family list is the collapsed "What exactly".
function prefsConfirmSummary(inventory){
 const n=['terminal-font','opened','editor-view','capture','dismissed','home-tab','notices'].reduce((a,id)=>a+prefsCount(inventory,id),0);
 if(!n)return 'Nothing is stored for the manager in this browser.';
 const closed=prefsCount(inventory,'dismissed'),tab=prefsCount(inventory,'home-tab')+prefsCount(inventory,'notices');
 const extra=(closed?` ${prefsPlural(closed,'closed warning shows','closed warnings show')} again and ${closed===1?'its lab reads':'their labs read'} Needs attention.`:'')+(tab?' Some items change in this tab only.':'');
 return `Reset forgets ${prefsPlural(n,'remembered item')} of this browser.${extra} Drafts, templates and Try again requests are kept.`;
}
// inventory: shell.js preferenceInventory(); display: {motion, contrast, forced}; font: the effective terminal size;
// homeWord: 'recent' | 'all' | '' (prefsHomeWord). Only the font number and that word are ever interpolated.
function prefsMarkup(inventory,display,font,homeWord){
 const inv=inventory||{},d=display||{},blocked=!!inv.blocked,writable=inv.writable!==false,c=id=>prefsCount(inv,id);
 const size=PREFS_FONT_SIZES.includes(Number(font))?Number(font):PREFS_FONT_DEFAULT;
 const displayHtml=`<section><h3>Display settings the manager follows</h3><p class="caption">From your system or browser; the manager stores nothing for them.</p><dl class="kv">${prefsRow('Reduced motion',prefsOnOff(d.motion))}${prefsRow('More contrast',prefsOnOff(d.contrast))}${prefsRow('Forced colours',prefsOnOff(d.forced))}</dl><p class="caption">${PREFS_APPEARANCE}</p></section>`;
 const resetBtn=`<button type="button" class="button secondary" id="prefs-reset"${blocked?` disabled title="${esc(PREFS_BLOCKED_RESET)}"`:''}>Reset browser preferences…</button>`;
 const resetHtml=`<section><div class="dialog-actions">${blocked?`<span class="caption">${PREFS_BLOCKED_RESET}</span>`:''}${resetBtn}</div>`
  +(blocked?'':`<div id="prefs-reset-confirm" class="banner warn" role="group" aria-label="Confirm reset" hidden><div><p>${esc(prefsConfirmSummary(inv))}</p><details><summary>What exactly</summary><p>${esc(prefsConfirmSentence(inv))}</p></details></div><div class="dialog-actions"><button type="button" class="button secondary" id="prefs-reset-keep">Keep</button><button type="button" class="button danger" id="prefs-reset-go">Reset</button></div></div>`)+'</section>';
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
 const inventory=preferenceInventory();
 body.innerHTML=prefsMarkup(inventory,prefsDisplay(),terminalFontPreference(),prefsHomeWord(inventory));
 const select=$('pref-terminal-font');
 if(select)select.onchange=()=>{
  const v=Number(select.value);
  if(setTerminalFontPreference(v))prefsStatus(`Terminal text size ${v} px. Applies to terminals opened from now on; open terminals keep theirs.`);
  else{select.value=String(terminalFontPreference());prefsStatus(PREFS_STATUS_KEPT);}
 };
 const open=$('prefs-reset'),confirm=$('prefs-reset-confirm'),keep=$('prefs-reset-keep'),go=$('prefs-reset-go');
 if(open&&confirm)open.onclick=()=>{confirm.hidden=false;prefsFocus('prefs-reset-keep');};
 if(keep&&confirm)keep.onclick=()=>{confirm.hidden=true;prefsFocus('prefs-reset');};
 if(go)go.onclick=prefsReset;
}
// The only caller of resetPreferences: the Reset button of the confirm row.
function prefsReset(){
 const result=resetPreferences()||{cleared:0};
 prefsRender();prefsFocus('prefs-reset');
 if(typeof render==='function')render();   // Home cards and lab banners read the dismissed warnings again now, not at the next poll
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
