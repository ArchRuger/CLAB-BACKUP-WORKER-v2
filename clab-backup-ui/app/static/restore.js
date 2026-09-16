'use strict';
// Apply a saved configuration to a running Junos node. The browser sends only a source
// reference (a Git commit + path, or a backup job id) and the chosen node names; the
// manager owns the SSH, the load-override + confirmed-commit mechanism and the redaction.
const restoreActiveJob = new Set(['queued', 'preflight', 'backing_up', 'applying', 'confirming', 'verifying']);
const restoreJobLabels = {
 queued: 'Restore queued', preflight: 'Checking the lab and nodes', backing_up: 'Backing up current configuration',
 applying: 'Replacing configuration', confirming: 'Confirming the commit', verifying: 'Verifying the result',
 succeeded: 'Configuration applied successfully', partial: 'Some nodes restored', needs_attention: 'Applied — post-check needs attention',
 failed: 'Restore failed', preflight_failed: 'Preflight failed', interrupted: 'Restore interrupted', dismissed: 'Restore dismissed'};
const restoreTargetLabels = {
 pending: 'Waiting', backing_up: 'Backing up first', applying: 'Loading configuration', confirming: 'Confirming commit',
 applied: 'Applied (confirmed)', applied_unverified: 'Applied — verify by hand', verified: 'Applied and verified',
 verify_mismatch: 'Applied — differences remain', rollback_expected: 'Rolled back automatically', failed: 'Not changed',
 ineligible: 'Skipped', interrupted: 'Interrupted'};
const restoreGoodTarget = new Set(['applied', 'verified']);
const restoreBadTarget = new Set(['failed', 'rollback_expected', 'ineligible', 'verify_mismatch']);
let restoreWatch = null, restoreWatchTimer = null, restoreDialogJob = '';

function restoreRequestId() {
 const bytes = new Uint8Array(16); crypto.getRandomValues(bytes);
 return Array.from(bytes, n => n.toString(16).padStart(2, '0')).join('');
}
function restoreBadge(status, labels) {
 const cls = ['succeeded', 'verified', 'applied'].includes(status) ? 'good'
  : restoreActiveJob.has(status) ? 'running'
  : ['failed', 'preflight_failed', 'rollback_expected'].includes(status) ? 'bad' : 'warn';
 return `<span class="badge ${cls}">${esc(labels[status] || status)}</span>`;
}
function restoreSourceLabel(source) {
 if (!source) return 'Saved configuration';
 if (source.type === 'git') return 'Git version · ' + (String(source.commit || '').slice(0, 10) || source.path || '');
 if (source.type === 'backup') return 'Saved capture · ' + String(source.backup_job_id || '').slice(0, 10);
 return 'Saved configuration';
}

// Entry point from the Git version view.
async function restoreFromVersion(labId, source, label) {
 await restoreReview(labId, source, label);
}

async function restoreReview(labId, source, label) {
 const dialog = opDialog('restore-review-dialog', 'Replace running configuration',
  '<p role="status">Checking the lab, the saved version and each running node…</p>');
 let review;
 try { review = await json('/labs/' + encodeURIComponent(labId) + '/restore/preflight', 'POST', { source }); }
 catch (error) {
  dialog.querySelector('p').innerHTML = `<span class="form-error" role="alert">${esc(error.message)}</span>`;
  return;
 }
 const rows = review.targets || [], eligible = rows.filter(r => r.eligible);
 const requestId = restoreRequestId(), confirmDefault = 5;
 const targetRow = r => {
  const detail = r.eligible
   ? (r.matches_saved ? 'Junos · already matches the saved state'
     : 'Junos · ' + (r.pending_changes != null ? r.pending_changes + ' change(s) to apply' : 'ready'))
   : esc(r.reason || 'Not eligible');
  return `<label class="checkbox-label restore-target ${r.eligible ? '' : 'disabled'}">
   <input type="checkbox" name="restore-node" value="${esc(r.name)}" ${r.eligible ? 'checked' : 'disabled'}>
   <span><strong>${esc(r.short_name || r.name)}</strong> <small>${detail}</small></span></label>`;
 };
 dialog.innerHTML = `<div class="dialog-head"><span class="eyebrow">LIVE CONFIGURATION RESTORE</span><button class="icon-button" data-op-close aria-label="Close">×</button></div>
 <h2>Replace running configuration</h2>
 <p>This loads the selected saved configuration onto the running device. The node is <strong>not</strong> rebooted or redeployed. The current configuration is backed up first.</p>
 <dl class="health-grid"><dt>Source</dt><dd>${esc(label || restoreSourceLabel(review.source))}</dd>
 <dt>Saved at</dt><dd>${esc(review.source?.captured_at ? utcDisplay(review.source.captured_at) : 'unknown')}</dd>
 <dt>Target lab</dt><dd>${esc((state.labs || []).find(l => l.id === labId)?.name || labId)}</dd></dl>
 <fieldset class="restore-targets"><legend>Target nodes</legend>${rows.map(targetRow).join('') || '<p>No saved node maps to a running node in this lab.</p>'}</fieldset>
 <ul class="restore-safety">
  <li>The current configuration is backed up first; a node whose backup fails is not changed.</li>
  <li>The configuration is validated (commit check) and activated with a commit that rolls back on its own if management is lost.</li>
  <li>Unsupported or unreachable nodes are not modified.</li>
 </ul>
 <details class="restore-advanced"><summary>Safety options</summary>
  <label for="restore-confirm-minutes">Automatic rollback if not confirmed (minutes)</label>
  <input id="restore-confirm-minutes" type="number" min="2" max="60" value="${confirmDefault}">
  <p class="form-help">After the configuration is loaded the manager reconnects to prove the node is reachable, then confirms. If it cannot reconnect in time, the node rolls back to the pre-restore state.</p></details>
 <label id="restore-ack-label" class="checkbox-label"><input id="restore-ack" type="checkbox"> I understand the running configuration on the selected nodes will be replaced with the saved configuration.</label>
 <p class="form-error" role="alert"></p>
 <div class="dialog-actions"><button class="button secondary" data-op-close>Cancel</button>
  <button class="button danger" id="restore-run" ${eligible.length ? '' : 'disabled'}>Replace configuration</button></div>`;
 dialog.querySelectorAll('[data-op-close]').forEach(b => b.onclick = () => dialog.close());
 $('restore-run').onclick = () => opTask(dialog, async () => {
  const chosen = [...dialog.querySelectorAll('[name="restore-node"]:checked')].map(i => i.value);
  if (!chosen.length) throw new Error('Select at least one eligible node.');
  if (!$('restore-ack').checked) throw new Error('Acknowledge that the running configuration will be replaced.');
  const minutes = Math.min(60, Math.max(2, parseInt($('restore-confirm-minutes').value, 10) || confirmDefault));
  const job = await json('/labs/' + encodeURIComponent(labId) + '/restore', 'POST',
   { request_id: requestId, source, node_names: chosen, confirm_minutes: minutes, acknowledge: true });
  dialog.close();
  await restoreShowJob(job.id, job); await refresh();
 });
}

async function restoreShowJob(id, known) {
 const job = known || await (await api('/restore/jobs/' + encodeURIComponent(id))).json();
 restoreDialogJob = id;
 const dialog = opDialog('restore-job-dialog', 'Live configuration restore', '<div id="restore-job-detail"></div>');
 dialog.onclose = () => { restoreDialogJob = ''; if (restoreWatch === id) restoreStopWatch(); };
 dialog.querySelector('[data-op-close]').onclick = () => dialog.close();
 restoreRenderJob(job);
 if (restoreActiveJob.has(job.status)) restoreStartWatch(job);
}
function restoreRenderJob(job) {
 if (restoreDialogJob !== job.id || !$('restore-job-dialog')?.open) return;
 const target = t => `<div class="restore-target-row">${restoreBadge(t.status, restoreTargetLabels)}
  <strong>${esc(t.short_name || t.name)}</strong><p>${esc(t.message || '')}</p>
  ${t.status === 'verify_mismatch' && (t.missing_statements || t.extra_statements)
   ? `<p class="form-help">${esc(t.missing_statements || 0)} desired statement(s) missing, ${esc(t.extra_statements || 0)} unexpected remaining.</p>` : ''}</div>`;
 $('restore-job-detail').innerHTML = `<div class="git-job-summary">${restoreBadge(job.status, restoreJobLabels)}<p>${esc(job.message || '')}</p></div>
  <div class="restore-targets-status">${(job.targets || []).map(target).join('')}</div>
  <dl class="health-grid">${job.pre_backup_job_id ? `<dt>Pre-restore backup</dt><dd class="mono">${esc(job.pre_backup_job_id.slice(0, 12))}</dd>` : ''}
   ${job.post_backup_job_id ? `<dt>Verification backup</dt><dd class="mono">${esc(job.post_backup_job_id.slice(0, 12))}</dd>` : ''}
   <dt>Rollback timer</dt><dd>${esc(job.confirm_minutes || 5)} min</dd></dl>
  ${restoreActiveJob.has(job.status) ? '<p class="form-help" role="status">You can close this window; the restore continues and its result stays in the action log.</p>' : ''}`;
}
function restoreStartWatch(job) {
 if (restoreWatch === job.id) return; restoreStopWatch();
 restoreWatch = job.id;
 const poll = async () => {
  if (restoreWatch !== job.id) return;
  try {
   const value = await (await api('/restore/jobs/' + encodeURIComponent(job.id))).json();
   if (restoreWatch !== job.id) return;
   restoreRenderJob(value);
   if (restoreActiveJob.has(value.status)) restoreWatchTimer = setTimeout(poll, 1500);
   else { restoreStopWatch(); await refresh(); }
  } catch (error) { restoreStopWatch(); }
 };
 restoreWatchTimer = setTimeout(poll, 1200);
}
function restoreStopWatch() { clearTimeout(restoreWatchTimer); restoreWatch = null; }
