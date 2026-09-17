'use strict';
// Apply a saved configuration to a running Junos node. The browser sends only a source
// reference (a Git commit + path, a repository folder, or a backup job id) and the chosen node
// names; the manager owns the SSH, the load-override + confirmed-commit mechanism and the
// redaction. Every label here is the student's; the backend's own words stay under Details.
const restoreActiveJob = new Set(['queued', 'preflight', 'backing_up', 'applying', 'confirming', 'verifying']);
const restoreJobLabels = {
 queued: 'Waiting to start', preflight: 'Checking the devices…', backing_up: 'Backing up current configurations…',
 applying: 'Applying the saved configuration…', confirming: 'Checking that the devices answer…', verifying: 'Verifying the result…',
 succeeded: 'Configuration replaced', partial: 'Configuration replaced on some devices',
 needs_attention: 'Configuration replaced — the follow-up check needs attention', failed: 'Configuration not replaced',
 preflight_failed: 'Could not start — the checks failed', interrupted: 'Interrupted — the manager restarted; check the devices',
 dismissed: 'Dismissed'};
const restoreTargetLabels = {
 pending: 'Waiting', backing_up: 'Backing up…', applying: 'Applying…', confirming: 'Confirming…',
 applied: 'Replaced', verified: 'Replaced and verified', applied_unverified: 'Replaced — not verified',
 verify_mismatch: 'Replaced — differences remain', rollback_expected: 'Rolled back — unchanged', failed: 'Not changed',
 ineligible: 'Skipped', interrupted: 'Interrupted — check this device'};
const restoreGoodTarget = new Set(['applied', 'verified']);
const restoreBadTarget = new Set(['failed', 'rollback_expected', 'ineligible', 'verify_mismatch']);
const restoreReplacedTarget = new Set(['applied', 'verified', 'applied_unverified', 'verify_mismatch']);
const restoreAttentionTarget = new Set(['applied_unverified', 'verify_mismatch', 'interrupted']);
const restoreUnchangedTarget = new Set(['failed', 'rollback_expected', 'ineligible']);
// Preflight reasons, matched by prefix; anything unknown is shown verbatim.
const restoreReasons = [
 ['No running node in this lab matches this saved node', 'No running device in this lab has this name.'],
 ['Live restore is not supported for this platform', 'Only Junos devices can be updated this way for now.'],
 ['The saved platform does not match the running node', 'The saved configuration is for a different kind of device.'],
 ['The node is not currently running or discovery is stale', 'This device is not running, or the lab status is out of date.'],
 ['Assign NOS credentials to this node first', 'Add login credentials for this device first (Advanced › Credentials).'],
 ['Refresh VM discovery before restoring', 'Refresh the lab list (Manager ▾ › Refresh lab list), then try again.'],
 ['SSH probe failed', 'The device did not answer over SSH.']];
let restoreWatch = null, restoreWatchTimer = null, restoreDialogJob = '', restoreLastJob = null, restorePaused = false;

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
 if (source.type === 'git') return 'Saved version · ' + (String(source.commit || '').slice(0, 10) || source.path || '');
 if (source.type === 'folder') return 'Saved version · ' + String(source.path || '').replace(/\/latest$/, '');
 if (source.type === 'backup') return 'Backup · ' + String(source.backup_job_id || '').slice(0, 10);
 return 'Saved configuration';
}
function restoreReasonLabel(reason) {
 const text = String(reason || '');
 const match = restoreReasons.find(([prefix]) => text.startsWith(prefix));
 return match ? match[1] : text;
}
function restoreWhen(value) {
 if (!value) return '';
 return typeof relativeTime === 'function' ? relativeTime(value) : utcDisplay(value);
}
// What the change did, counted from the per-device outcomes.
function restoreResultSentence(job) {
 const targets = job.targets || [];
 if (restoreActiveJob.has(job.status) || !targets.length) return '';
 const replaced = targets.filter(t => restoreReplacedTarget.has(t.status)).length;
 const attention = targets.filter(t => restoreAttentionTarget.has(t.status)).length;
 const unchanged = targets.filter(t => restoreUnchangedTarget.has(t.status)).length;
 const plural = n => n === 1 ? 'device' : 'devices';
 const parts = [`Configuration replaced on ${replaced} ${plural(replaced)}.`];
 if (attention) parts.push(`${attention} ${plural(attention)} need${attention === 1 ? 's' : ''} attention.`);
 if (unchanged) parts.push(`${unchanged} ${plural(unchanged)} ${unchanged === 1 ? 'was' : 'were'} not changed.`);
 return parts.join(' ');
}
function restoreJobTitle(job) {
 if (restoreActiveJob.has(job.status)) return 'Applying saved configuration';
 if (job.status === 'succeeded') return 'Configuration replaced';
 if (job.status === 'partial' || job.status === 'needs_attention') return 'Configuration replaced — needs attention';
 if (job.status === 'interrupted') return 'Configuration change interrupted';
 if (job.status === 'dismissed') return 'Configuration change dismissed';
 return 'Configuration not replaced';
}

// Entry point from the Git version view.
async function restoreFromVersion(labId, source, label) {
 await restoreReview(labId, source, label);
}

// Entry point from the folder browser and the Saved versions list: apply a folder's latest saved
// state to the running lab directly, without pointing the lab at that folder first.
async function restoreFromFolder(labId, folderPrefix, tree) {
 const prefix = String(folderPrefix || '').replace(/\/+$/, '');
 if (!prefix) { notify('Choose a saved folder to apply.'); return; }
 const name = prefix.split('/').filter(Boolean).pop() || prefix;
 const repoName = tree && tree.repository ? gitRepoName(tree.repository) : '';
 const friendly = typeof savedVersionName === 'function' ? savedVersionName(prefix) : name;
 await restoreReview(labId, { type: 'folder', path: prefix + '/latest' },
  friendly + ' · ' + (repoName ? repoName + ' › ' : '') + prefix);
}

async function restoreReview(labId, source, label) {
 const dialog = opDialog('restore-review-dialog', 'Replace running configuration',
  '<p role="status">Checking the saved configuration and your devices…</p>');
 let review;
 try { review = await json('/labs/' + encodeURIComponent(labId) + '/restore/preflight', 'POST', { source }); }
 catch (error) {
  dialog.innerHTML = `<div class="dialog-head"><h2>Replace running configuration</h2><button class="icon-button" data-op-close aria-label="Close">×</button></div>
   <p role="status">The saved configuration cannot be applied right now.</p><p class="form-error" role="alert">${esc(error.message)}</p>
   <div class="dialog-actions"><button class="button secondary" data-op-close>Close</button></div>`;
  dialog.querySelectorAll('[data-op-close]').forEach(b => b.onclick = () => dialog.close());
  return;
 }
 const rows = review.targets || [], eligible = rows.filter(r => r.eligible), skipped = rows.filter(r => !r.eligible && r.reason);
 const requestId = restoreRequestId(), confirmDefault = 5;
 const targetRow = r => {
  const detail = r.eligible
   ? (r.matches_saved ? 'Already matches — nothing to change'
     : r.pending_changes != null ? r.pending_changes + ' differences from the running configuration' : 'Ready to apply')
   : 'Skipped — ' + restoreReasonLabel(r.reason || 'Not eligible');
  return `<label class="checkbox-label restore-target ${r.eligible ? '' : 'disabled'}">
   <input type="checkbox" name="restore-node" value="${esc(r.name)}" ${r.eligible ? 'checked' : 'disabled'}>
   <span><strong>${esc(r.short_name || r.name)}</strong> <small>${esc(detail)}</small></span></label>`;
 };
 const savedAt = review.source?.captured_at ? restoreWhen(review.source.captured_at) : '';
 dialog.innerHTML = `<div class="dialog-head"><h2>Replace running configuration</h2><button class="icon-button" data-op-close aria-label="Close">×</button></div>
 <p>Lab: <strong>${esc((state.labs || []).find(l => l.id === labId)?.name || '')}</strong></p>
 <p>Source: <strong>${esc(label || restoreSourceLabel(review.source))}</strong>${savedAt ? ` <span class="caption" title="${esc(utcDisplay(review.source.captured_at))}">· saved ${esc(savedAt)}</span>` : ''}</p>
 <p>Current configurations are backed up first. The devices are not rebooted.</p>
 <fieldset class="restore-targets"><legend>Devices</legend>${rows.map(targetRow).join('') || '<p>None of the devices in this saved configuration are running in this lab.</p>'}</fieldset>
 ${skipped.length ? `<details class="caption"><summary>Details</summary><ul>${skipped.map(r => `<li><strong>${esc(r.short_name || r.name)}</strong>: ${esc(r.reason)}</li>`).join('')}</ul></details>` : ''}
 <ul class="restore-safety">
  <li>Each device's current configuration is backed up first. A device whose backup fails is left unchanged.</li>
  <li>The devices are not rebooted. The new configuration is checked before it is activated and is undone on its own if the device cannot be reached within <span id="restore-minutes-text">${confirmDefault}</span> minutes.</li>
  <li>Devices that are skipped above are not touched.</li>
 </ul>
 <details class="restore-advanced"><summary>Advanced options</summary>
  <label for="restore-confirm-minutes">Undo automatically if the device cannot be reached again within (minutes)</label>
  <input id="restore-confirm-minutes" type="number" min="2" max="60" value="${confirmDefault}">
  <p class="form-help">After the configuration is loaded, the manager reconnects to prove the device is reachable, then confirms the change. If it cannot reconnect in time, the device returns to its previous configuration on its own.</p></details>
 <label id="restore-ack-label" class="checkbox-label"><input id="restore-ack" type="checkbox"> I understand the running configuration on the selected devices will be replaced.</label>
 <p class="form-error" role="alert"></p>
 <div class="dialog-actions"><button class="button secondary" data-op-close>Cancel</button>
  <button class="button danger" id="restore-run" ${eligible.length ? '' : 'disabled'}>Replace configurations</button></div>`;
 dialog.querySelectorAll('[data-op-close]').forEach(b => b.onclick = () => dialog.close());
 const minutesField = $('restore-confirm-minutes');
 if (minutesField) minutesField.oninput = () => { const text = $('restore-minutes-text'); if (text) text.textContent = String(Math.min(60, Math.max(2, parseInt(minutesField.value, 10) || confirmDefault))); };
 $('restore-run').onclick = () => opTask(dialog, async () => {
  const chosen = [...dialog.querySelectorAll('[name="restore-node"]:checked')].map(i => i.value);
  if (!chosen.length) throw new Error('Choose at least one device.');
  if (!$('restore-ack').checked) throw new Error('Tick the box to confirm that the running configuration will be replaced.');
  const minutes = Math.min(60, Math.max(2, parseInt($('restore-confirm-minutes').value, 10) || confirmDefault));
  const job = await json('/labs/' + encodeURIComponent(labId) + '/restore', 'POST',
   { request_id: requestId, source, node_names: chosen, confirm_minutes: minutes, acknowledge: true });
  dialog.close();
  await restoreShowJob(job.id, job); await refresh();
 });
}

// Re-enterable from the lab banner ([View progress] / [Details]) and from the Progress tab.
async function restoreShowJob(id, known) {
 const job = known || await (await api('/restore/jobs/' + encodeURIComponent(id))).json();
 restoreDialogJob = id; restorePaused = false;
 const dialog = opDialog('restore-job-dialog', restoreJobTitle(job), '<div id="restore-job-detail"></div>');
 dialog.onclose = () => { restoreDialogJob = ''; if (restoreWatch === id) restoreStopWatch(); };
 dialog.querySelector('[data-op-close]').onclick = () => dialog.close();
 restoreRenderJob(job);
 if (restoreActiveJob.has(job.status)) restoreStartWatch(job);
}
function restoreRenderJob(job) {
 if (restoreDialogJob !== job.id || !$('restore-job-dialog')?.open) return;
 restoreLastJob = job;
 const heading = $('restore-job-dialog').querySelector('h2'); if (heading) heading.textContent = restoreJobTitle(job);
 const target = t => `<div class="restore-target-row">${restoreBadge(t.status, restoreTargetLabels)}
  <strong>${esc(t.short_name || t.name)}</strong>
  ${t.status === 'verify_mismatch' && (t.missing_statements || t.extra_statements)
   ? `<p class="form-help">${esc(t.missing_statements || 0)} expected configuration lines are missing and ${esc(t.extra_statements || 0)} unexpected lines remain.</p>` : ''}
  ${t.status === 'rollback_expected' ? '<p class="form-help">The device did not answer in time, so it returned to its previous configuration.</p>' : ''}
  ${t.status === 'ineligible' && t.message ? `<p class="form-help">${esc(restoreReasonLabel(t.message))}</p>` : ''}
  ${t.message ? `<details class="caption"><summary>Details</summary><p>${esc(t.message)}</p></details>` : ''}</div>`;
 const backupLink = (id, label) => id ? `<dt>${label}</dt><dd><button type="button" class="link-button mono" data-restore-backup="${esc(id)}">${esc(id.slice(0, 12))}</button></dd>` : '';
 $('restore-job-detail').innerHTML = `<div class="git-job-summary">${restoreBadge(job.status, restoreJobLabels)}<p>${esc(restoreResultSentence(job))}</p></div>
  <div class="restore-targets-status">${(job.targets || []).map(target).join('')}</div>
  <details class="restore-job-details"><summary>Details</summary><dl class="health-grid">
   ${backupLink(job.pre_backup_job_id, 'Backup taken before the change')}${backupLink(job.post_backup_job_id, 'Backup taken after the change')}
   <dt>Automatic undo window</dt><dd>${esc(job.confirm_minutes || 5)} minutes</dd>
   <dt>Status</dt><dd>${esc(job.status || '')}</dd><dt>Message</dt><dd>${esc(job.message || '')}</dd></dl></details>
  ${restoreActiveJob.has(job.status) ? (restorePaused
   ? '<p class="form-help" role="status">Status updates paused. <button type="button" class="link-button" id="restore-resume">Refresh</button></p>'
   : '<p class="form-help" role="status">You can close this window. The change keeps running in the background; its result is shown in the lab header and under Advanced › Action logs.</p>') : ''}`;
 for (const button of $('restore-job-detail').querySelectorAll('[data-restore-backup]')) button.onclick = () => {
  $('restore-job-dialog').close();
  if (typeof showTab === 'function') showTab('backups');
  const capture = [...document.querySelectorAll('.job')].find(item => item.dataset.job === button.dataset.restoreBackup);
  if (capture) { capture.open = true; capture.scrollIntoView({ block: 'center', behavior: 'smooth' }); }
 };
 const resume = $('restore-resume'); if (resume) resume.onclick = () => { restorePaused = false; restoreStartWatch(job); };
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
  } catch (error) { restoreStopWatch(); restorePaused = true; if (restoreLastJob && restoreLastJob.id === job.id) restoreRenderJob(restoreLastJob); }
 };
 restoreWatchTimer = setTimeout(poll, 1200);
}
function restoreStopWatch() { clearTimeout(restoreWatchTimer); restoreWatch = null; }
