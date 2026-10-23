// preferences.js: the Browser preferences dialog markup and behaviour, and the shortcuts dialog's exclusion list
// (docs/parity-campaign/C09-DESIGN.md sections 3, 5 and 6). The dialog markup of index.html is built here from the design.
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const file=path.join(__dirname,'../app/static/preferences.js'),source=fs.readFileSync(file,'utf8');
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const NOT_STORED='The open folders of the save chooser and the Home filter are kept only while this page is open.';
function fam(counts,keys={}){
 const ids=['terminal-font','opened','dismissed','design-drafts','builder-drafts','builder-templates','editor-view','capture','home-tab','notices','active-lab','requests','save-requests','op-return'];
 return ids.map(id=>({id,kind:'x',reset:true,count:counts[id]||0,keys:keys[id]||[]}));
}
function harness(over={}){
 const els={},calls={reset:0,setFont:[],shown:0,focus:[]};
 const el=id=>{if(!els[id]){els[id]={id,hidden:false,textContent:'',innerHTML:'',open:false,value:'',onclick:null,onchange:null,focus(){calls.focus.push(id);},showModal(){this.open=true;calls.shown++;}};}return els[id];};
 for(const id of ['preferences-dialog','shortcuts-dialog','preferences-body','prefs-status','manager-preferences','manager-shortcuts'])el(id);
 const body=els['preferences-body'];
 let html='';
 Object.defineProperty(body,'innerHTML',{get:()=>html,set(v){
  html=v;
  for(const id of ['pref-terminal-font','prefs-reset','prefs-reset-confirm','prefs-reset-keep','prefs-reset-go']){
   delete els[id];
   if(v.includes(`id="${id}"`)){const e=el(id);if(id==='prefs-reset-confirm')e.hidden=/id="prefs-reset-confirm"[^>]*hidden/.test(v);}
  }
  if(els['pref-terminal-font'])els['pref-terminal-font'].value=(v.match(/<option value="(\d+)" selected/)||[])[1]||'';
 }});
 let inventory=over.inventory||{blocked:false,writable:true,families:fam({})};
 const ctx={$:id=>els[id]||null,esc,
  preferenceInventory:()=>inventory,
  resetPreferences:()=>{calls.reset++;const r=over.resetResult||{cleared:3,blocked:false};inventory={blocked:false,writable:true,families:fam({})};return r;},
  mediaMatches:q=>(over.media||{})[q]||false,terminalFontPreference:()=>over.font||14,
  setTerminalFontPreference:v=>{calls.setFont.push(v);return over.setOk!==false;},homeTab:()=>over.home||'recent'};
 const context=vm.createContext(ctx);vm.runInContext(source,context);
 return {ctx,context,els,calls};
}
const run=(h,code)=>vm.runInContext(code,h.context);
test('preferences.js loads in a bare context and wires only its own two menu items',()=>{
 const h=harness();
 assert.equal(typeof h.els['manager-preferences'].onclick,'function');assert.equal(typeof h.els['manager-shortcuts'].onclick,'function');
});
test('the markup renders every row with its count words, the two Kept by Reset groups, display rows and the appearance line',()=>{
 const h=harness();
 const inv={blocked:false,writable:true,families:fam({'terminal-font':1,opened:3,dismissed:2,'design-drafts':1,'builder-drafts':2,'builder-templates':1,'editor-view':4,capture:3,'home-tab':1,notices:2,requests:1,'save-requests':1,'op-return':1,'active-lab':1},{capture:['clab.capture.l.node:r1','clab.capture.l.link:a','clab.capture.openas']})};
 const m=run(h,`prefsMarkup(${JSON.stringify(inv)},{motion:true,contrast:false,forced:false},16,'all')`);
 for(const s of ['Terminal text size','16 px','for 3 labs','Closed warnings about failed operations','4 settings','for 2 devices and links','Kept by Reset','Network design drafts','1 · discard them on the Network design card','2 · Drafts… in the lab builder','Lab builder templates','All labs','Closed notices','Try again requests','A save being sent','Return to the lab builder','The lab that was open','Reduced motion</dt><dd>on','More contrast</dt><dd>off','Forced colours</dt><dd>off',NOT_STORED,'Appearance: light. The terminal page is dark by design; there is no dark mode setting.'])assert.ok(m.includes(s),s);
 assert.equal((m.match(/Kept by Reset/g)||[]).length,2);
 assert.match(m,/<option value="14">14 px \(default\)<\/option>/);assert.match(m,/<option value="16" selected>/);
 assert.doesNotMatch(m,/<select[^>]*disabled/);assert.doesNotMatch(m,/id="prefs-reset"[^>]*disabled/);
 assert.doesNotMatch(m,/clab\.|react-topoviewer|clab-builder:/,'keys and ids never appear');
});
test('empty store: defaults and none; only the font number and the Home tab word are interpolated, and not raw',()=>{
 const h=harness();
 const m=run(h,`prefsMarkup({blocked:false,writable:true,families:${JSON.stringify(fam({}))}},{},14,'<img onerror=x>')`);
 assert.match(m,/default \(14 px\)/);assert.match(m,/Home list tab<\/dt><dd>default</);assert.doesNotMatch(m,/<img/);
 assert.match(m,/Remembered capture choices<\/dt><dd>none/);
 const f=run(h,`prefsMarkup({blocked:false,writable:true,families:${JSON.stringify(fam({'terminal-font':1}))}},{},'<b>','')`);
 assert.doesNotMatch(f,/<b>/);
});
test('blocked body: one sentence, no select, Reset disabled with its reason, display section kept',()=>{
 const h=harness();
 const m=run(h,"prefsMarkup({blocked:true,writable:false,families:[]},{motion:false},14,'')");
 assert.ok(m.includes('This browser does not let the page read or keep its storage (a private window, or site data blocked). Nothing is remembered between visits, so there is nothing to show or reset.'));
 assert.doesNotMatch(m,/<select/);
 assert.match(m,/id="prefs-reset" disabled title="Not available: storage is blocked in this browser\."/);
 assert.ok(m.includes('<span class="caption">Not available: storage is blocked in this browser.</span>'));assert.ok(m.includes('Reduced motion'));
});
test('cannot-store body: only the select is disabled, with the full-store sentence; Reset stays enabled',()=>{
 const h=harness();
 const m=run(h,`prefsMarkup({blocked:false,writable:false,families:${JSON.stringify(fam({opened:1}))}},{},14,'')`);
 assert.match(m,/<select id="pref-terminal-font" disabled>/);
 assert.ok(m.includes('This browser is not letting the page store anything new (storage full or read-only).'));
 assert.doesNotMatch(m,/id="prefs-reset" disabled/);
});
test('the confirm sentence names the counts, the Needs attention clause, the tab-only items and the kept items; singular and empty',()=>{
 const h=harness();
 const s=inv=>run(h,`prefsConfirmSentence({families:${JSON.stringify(fam(inv))}})`);
 assert.equal(s({'terminal-font':1,opened:2,'editor-view':1,capture:1,dismissed:1,'home-tab':1,notices:1}),
  'In this browser this forgets the terminal text size, the Last opened times of 2 labs, the editor view settings, the remembered capture choices and which warnings about failed operations you closed (1 warning): those warnings show again and their labs read Needs attention until you close them again. In this tab only, it forgets the Home list tab and the closed notices; other open tabs keep theirs. Drafts, templates and Try again requests are kept.');
 assert.equal(s({opened:1}),'In this browser this forgets the Last opened times of 1 lab. Drafts, templates and Try again requests are kept.');
 assert.equal(s({'design-drafts':2}),'Nothing is stored for the manager in this browser.');
});
test('opening empties the stale status, renders, then shows the dialog; the shortcuts item shows its dialog',()=>{
 const h=harness();h.els['prefs-status'].textContent='old sentence';
 h.els['manager-preferences'].onclick();
 assert.equal(h.els['prefs-status'].textContent,'');assert.equal(h.calls.shown,1);assert.match(h.els['preferences-body'].innerHTML,/pref-terminal-font/);
 h.els['manager-shortcuts'].onclick();assert.equal(h.els['shortcuts-dialog'].open,true);assert.equal(h.calls.shown,2);
});
test('the size select writes through the helper and reports; a failed write reverts and says so',()=>{
 let h=harness({font:14});h.els['manager-preferences'].onclick();
 h.els['pref-terminal-font'].value='16';h.els['pref-terminal-font'].onchange();
 assert.deepEqual(h.calls.setFont,[16]);
 assert.equal(h.els['prefs-status'].textContent,'Terminal text size 16 px. Applies to terminals opened from now on; open terminals keep theirs.');
 h=harness({font:14,setOk:false});h.els['manager-preferences'].onclick();
 h.els['pref-terminal-font'].value='17';h.els['pref-terminal-font'].onchange();
 assert.equal(h.els['pref-terminal-font'].value,'14');assert.equal(h.els['prefs-status'].textContent,'This browser does not let the page keep this setting.');
});
test('reset flow: the confirm row opens on Keep; Keep hides it and focuses Reset…; Reset calls the helper once, re-renders and reports',()=>{
 const h=harness({inventory:{blocked:false,writable:true,families:fam({opened:3,dismissed:2})}});
 h.els['manager-preferences'].onclick();
 assert.equal(h.els['prefs-reset-confirm'].hidden,true);
 h.els['prefs-reset'].onclick();
 assert.equal(h.els['prefs-reset-confirm'].hidden,false);assert.equal(h.calls.focus.at(-1),'prefs-reset-keep');
 assert.match(h.els['preferences-body'].innerHTML,/Needs attention/);
 h.els['prefs-reset-keep'].onclick();
 assert.equal(h.els['prefs-reset-confirm'].hidden,true);assert.equal(h.calls.focus.at(-1),'prefs-reset');assert.equal(h.calls.reset,0);
 h.els['prefs-reset'].onclick();h.els['prefs-reset-go'].onclick();
 assert.equal(h.calls.reset,1);assert.equal(h.calls.focus.at(-1),'prefs-reset');
 assert.equal(h.els['prefs-status'].textContent,'Browser preferences reset: 3 items cleared. Terminals opened from now on use the default text size.');
 assert.match(h.els['preferences-body'].innerHTML,/default \(14 px\)/);
});
test('reset wording: 1 item, 0 items',()=>{
 for(const [n,w] of [[1,'1 item'],[0,'0 items']]){
  const h=harness({resetResult:{cleared:n,blocked:false}});h.els['manager-preferences'].onclick();h.els['prefs-reset'].onclick();h.els['prefs-reset-go'].onclick();
  assert.ok(h.els['prefs-status'].textContent.includes(`reset: ${w} cleared.`),h.els['prefs-status'].textContent);
 }
});
test('the dialog reads storage only through the shell.js helpers: no stand-ins, no typeof guards on them (their storage claims are pinned in test_shell_ui.js)',()=>{
 assert.doesNotMatch(source,/FALLBACK|prefsFallback/);
 for(const name of ['preferenceInventory','resetPreferences','mediaMatches','terminalFontPreference','setTerminalFontPreference','homeTab'])assert.doesNotMatch(source,new RegExp(`typeof ${name}\\b`),name);
 const h=harness({media:{'(prefers-reduced-motion: reduce)':true}});
 assert.deepEqual(JSON.parse(JSON.stringify(run(h,'prefsDisplay()'))),{motion:true,contrast:false,forced:false});
});
test('SHORTCUT_EXCLUSIONS lists each file:line with a reason',()=>{
 const h=harness();const list=run(h,'SHORTCUT_EXCLUSIONS');
 assert.ok(list.length>=4);   // only real keydown sites that are not rows (the stale non-site entries were dropped; the pin in test_shell_ui.js checks each cite)
 for(const e of list){assert.match(e.source,/^[a-z-]+\.js:\d+$/);assert.ok(e.reason.length>10);}
 assert.equal(new Set(list.map(e=>e.source)).size,list.length);
});
test('source pins: no network, Store, storage names, global listeners or inline styles; one call of resetPreferences, in the helper',()=>{
 for(const re of [/\bfetch\(/,/\bapi\(/,/\bjson\(/,/document\.addEventListener/,/window\.addEventListener/,/localStorage/,/sessionStorage/,/===\s*['"]\?['"]/,/style=/])assert.doesNotMatch(source,re,String(re));
 assert.equal((source.match(/resetPreferences\(/g)||[]).length,1);
});

test('C09 fixes: the confirmation is one short paragraph with the total and a collapsed "What exactly" holding the family list',()=>{
 const h=harness();
 const inv={blocked:false,writable:true,families:fam({opened:2,dismissed:1,'design-drafts':4})};
 const m=run(h,`prefsMarkup(${JSON.stringify(inv)},{},14,'')`);
 const box=m.slice(m.indexOf('id="prefs-reset-confirm"'),m.indexOf('id="prefs-reset-go"'));
 assert.match(box,/<p>Reset forgets 3 remembered items of this browser\. Drafts, templates and Try again requests are kept\.<\/p><details><summary>What exactly<\/summary><p>In this browser this forgets the Last opened times of 2 labs/);
 assert.doesNotMatch(box,/<details open/,'collapsed');
 assert.equal(run(h,`prefsConfirmSummary({families:${JSON.stringify(fam({opened:1}))}})`),'Reset forgets 1 remembered item of this browser. Drafts, templates and Try again requests are kept.');
 assert.equal(run(h,`prefsConfirmSummary({families:${JSON.stringify(fam({'design-drafts':2}))}})`),'Nothing is stored for the manager in this browser.');
});
test('C09 fixes: after Reset the page behind the dialog is rendered at once (a guarded call)',()=>{
 const h=harness({inventory:{blocked:false,writable:true,families:fam({dismissed:2})}});let renders=0;
 h.context.render=()=>{renders++;};
 h.els['manager-preferences'].onclick();h.els['prefs-reset'].onclick();h.els['prefs-reset-go'].onclick();
 assert.equal(renders,1);
 const bare=harness({inventory:{blocked:false,writable:true,families:fam({dismissed:2})}});bare.els['manager-preferences'].onclick();bare.els['prefs-reset'].onclick();
 assert.doesNotThrow(()=>bare.els['prefs-reset-go'].onclick(),'no render() in a bare context');
});
