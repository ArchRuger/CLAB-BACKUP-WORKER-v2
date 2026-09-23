const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../app/static/diff-view.js'),'utf8');
function makeContext(){
 const context=vm.createContext({esc:value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))});
 vm.runInContext(source,context);return context;
}
test('diffMarkup renders a hunk header, gutters and a marker per row, and escapes configuration text',()=>{
 const context=makeContext();
 const diff={identical:false,added:1,removed:1,truncated:false,
  hunks:[{old_start:1,old_count:2,new_start:1,new_count:2,lines:[
   {type:'context',old:1,new:1,text:'set system host-name r1'},
   {type:'del',old:2,new:null,text:'set interfaces ge-0/0/0 <disable>'},
   {type:'add',old:null,new:2,text:'set interfaces ge-0/0/0 enable & ready'},
  ]}]};
 const html=context.diffMarkup(diff,{oldLabel:'Before',newLabel:'After'});
 assert.match(html,/1 added .* 1 removed/);
 assert.match(html,/@@ -1,2 \+1,2 @@/);
 assert.match(html,/class="diff-ctx"/);assert.match(html,/class="diff-del"/);assert.match(html,/class="diff-add"/);
 assert.match(html,/&lt;disable&gt;/);assert.doesNotMatch(html,/<disable>/);
 assert.match(html,/ready &amp; ready|enable &amp; ready/);
 // Gutters carry the right line numbers; a del row has no new-side number, an add row no old-side one.
 assert.match(html,/<td class="diff-gutter diff-gutter-old">2<\/td><td class="diff-gutter diff-gutter-new"><\/td><td class="diff-marker"[^>]*>-<\/td>/);
 assert.match(html,/<td class="diff-gutter diff-gutter-old"><\/td><td class="diff-gutter diff-gutter-new">2<\/td><td class="diff-marker"[^>]*>\+<\/td>/);
});
test('an identical diff and an empty diff both read as no differences, not as an empty table',()=>{
 const context=makeContext();
 assert.match(context.diffMarkup({identical:true,hunks:[],added:0,removed:0}),/Identical/);
 assert.match(context.diffMarkup(null),/No differences/);
});
test('a truncated diff shows its note as visible text',()=>{
 const context=makeContext();
 const html=context.diffMarkup({identical:false,hunks:[],added:0,removed:0,truncated:true,note:'Binary content is not shown as a line diff.'});
 assert.match(html,/Binary content is not shown as a line diff\./);
});
test('diffFileMarkup renders an added file as all additions and a removed file as all deletions, open by default',()=>{
 const context=makeContext();
 const added={identical:false,added:2,removed:0,truncated:false,hunks:[{old_start:0,old_count:0,new_start:1,new_count:2,lines:[
  {type:'add',old:null,new:1,text:'set system host-name new'},{type:'add',old:null,new:2,text:'set interfaces lo0 unit 0'}]}]};
 const html=context.diffFileMarkup('r5.cfg','added',added);
 assert.match(html,/<details class="diff-file" open>/);
 assert.match(html,/<span class="badge">added<\/span>/);
 assert.doesNotMatch(html,/diff-del/);
 const removed={identical:false,added:0,removed:1,truncated:false,hunks:[{old_start:1,old_count:1,new_start:0,new_count:0,lines:[
  {type:'del',old:1,new:null,text:'set system host-name old'}]}]};
 const removedHtml=context.diffFileMarkup('r6.cfg','removed',removed);
 assert.match(removedHtml,/<span class="badge">removed<\/span>/);
 assert.doesNotMatch(removedHtml,/diff-add/);
});
test('diffFileMarkup marks a suffix-renamed file as changed with its old name, and escapes an attack filename',()=>{
 const context=makeContext();
 const diff={identical:false,added:1,removed:1,truncated:false,hunks:[{old_start:1,old_count:1,new_start:1,new_count:1,lines:[
  {type:'del',old:1,new:null,text:'set a'},{type:'add',old:null,new:1,text:'set b'}]}]};
 const html=context.diffFileMarkup('r2.cfg','changed',diff,{renamedFrom:'r2.set'});
 assert.match(html,/renamed from r2\.set/);
 const attack=context.diffFileMarkup('<img src=x onerror=alert(1)>.cfg','changed',diff);
 assert.doesNotMatch(attack,/<img/);assert.match(attack,/&lt;img/);
});
test('an identical file collapses (not open) even when it is passed to diffFileMarkup',()=>{
 const context=makeContext();
 const html=context.diffFileMarkup('r7.cfg','changed',{identical:true,hunks:[],added:0,removed:0});
 assert.doesNotMatch(html,/<details class="diff-file" open>/);
 assert.match(html,/<details class="diff-file" >/);
});
test('style.css shrinks the diff gutters at narrow widths without dropping the wide-layout rule',()=>{
 const css=fs.readFileSync(path.join(__dirname,'../app/static/style.css'),'utf8');
 assert.match(css,/\.diff-col-gutter \{ width: 44px; \}/);
 assert.match(css,/@media \(max-width: 560px\) \{[^}]*\.diff-col-gutter \{ width: 26px; \}/s);
 assert.match(css,/\.diff-text \{[^}]*white-space: pre-wrap;[^}]*overflow-wrap: anywhere;/);
});
