'use strict';
// A real line-level diff for one saved configuration file, from the `diff` object the compare route
// (app/git_progress.py, textdiff.unified()) attaches to every file it returns: `{hunks, added,
// removed, truncated, identical}`, each hunk `{old_start, old_count, new_start, new_count, lines}`
// and each line `{type: 'context'|'add'|'del', old, new, text}`. Pure markup builders only: no DOM
// listeners at load, house style ('use strict', esc() on every interpolation). Loads before
// git-progress.js and restore.js, which call diffMarkup()/diffFileMarkup() to render every
// "Compared with…" and review pane.
function diffRowClass(type){return type==='add'?'diff-add':type==='del'?'diff-del':'diff-ctx';}
function diffRowMarker(type){return type==='add'?'+':type==='del'?'-':' ';}
function diffLineMarkup(row){
 return `<tr class="${diffRowClass(row.type)}"><td class="diff-gutter diff-gutter-old">${row.old==null?'':esc(String(row.old))}</td><td class="diff-gutter diff-gutter-new">${row.new==null?'':esc(String(row.new))}</td><td class="diff-marker" aria-hidden="true">${esc(diffRowMarker(row.type))}</td><td class="diff-text">${esc(row.text)}</td></tr>`;
}
function diffHunkHeader(hunk){return `@@ -${hunk.old_start},${hunk.old_count} +${hunk.new_start},${hunk.new_count} @@`;}
function diffHunkMarkup(hunk){
 return `<tr class="diff-hunk-head"><td colspan="4">${esc(diffHunkHeader(hunk))}</td></tr>${hunk.lines.map(diffLineMarkup).join('')}`;
}
// The whole diff of one file: a summary line, then every hunk as rows of a table with line-number
// gutters. `oldLabel`/`newLabel` caption the two sides (shown once, above the table); `maxHunks`
// caps how many hunks are rendered (the rest are noted, never silently dropped).
function diffMarkup(diff,options={}){
 if(!diff)return '<p class="diff-empty">No differences.</p>';
 const oldLabel=options.oldLabel||'Before',newLabel=options.newLabel||'After',maxHunks=options.maxHunks||200;
 if(diff.identical)return '<p class="diff-empty">Identical — nothing changed.</p>';
 const summary=`<p class="diff-summary">${esc(diff.added||0)} added · ${esc(diff.removed||0)} removed</p>`;
 const note=diff.truncated?`<p class="diff-note">${esc(diff.note||'This comparison was too large to show in full; it was shortened.')}</p>`:'';
 const hunks=diff.hunks||[];
 const shown=hunks.slice(0,maxHunks);
 const overflow=hunks.length>shown.length?`<p class="diff-note">${esc(hunks.length-shown.length)} more hunk(s) not shown.</p>`:'';
 const rows=shown.map(diffHunkMarkup).join('');
 const table=rows?`<table class="diff-table"><caption class="sr-only">${esc(oldLabel)} / ${esc(newLabel)}</caption><colgroup><col class="diff-col-gutter"><col class="diff-col-gutter"><col class="diff-col-marker"><col></colgroup><tbody>${rows}</tbody></table>`:'';
 return `${summary}${note}${table}${overflow}`;
}
// One file's `<details>` wrapper: open by default only when the file actually changed (status other
// than 'changed'/'added'/'removed' with no differences is not expected, but an identical diff still
// collapses). `labels` is the same {oldLabel, newLabel} passed to diffMarkup.
function diffStatusWord(status,renamedFrom){
 const word=status==='added'?'added':status==='removed'?'removed':'changed';
 return renamedFrom?word+' (renamed from '+renamedFrom+')':word;
}
function diffFileMarkup(name,status,diff,labels={}){
 const identical=!diff||diff.identical,open=!identical;
 return `<details class="diff-file" ${open?'open':''}><summary>${esc(name)} <span class="badge">${esc(diffStatusWord(status,labels.renamedFrom))}</span></summary><div class="diff-body">${diffMarkup(diff,labels)}</div></details>`;
}
