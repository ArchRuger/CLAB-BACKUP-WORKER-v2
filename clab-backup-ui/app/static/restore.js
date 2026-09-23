'use strict';
// Apply a saved configuration to a running node (Junos, Arista EOS or Cisco IOS XR). The browser
// sends only a source reference (a Git commit + path, a repository folder, or a backup job id) and
// the chosen node names; the manager owns the SSH, the per-platform replace-and-confirm mechanism
// and the redaction. Every label here is the student's; the backend's own words stay under Details.
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
 verify_mismatch: 'Replaced — differences remain', rollback_expected: 'Not confirmed — the device undoes it by itself',
 rolled_back: 'Undone — previous configuration is back', uncertain: 'Unknown — check this device', failed: 'Not changed',
 ineligible: 'Skipped', interrupted: 'Interrupted — check this device'};
const restoreGoodTarget = new Set(['applied', 'verified']);
const restoreBadTarget = new Set(['failed', 'ineligible', 'verify_mismatch', 'rolled_back']);
const restoreReplacedTarget = new Set(['applied', 'verified', 'applied_unverified', 'verify_mismatch']);
const restoreAttentionTarget = new Set(['applied_unverified', 'verify_mismatch', 'interrupted', 'uncertain', 'rollback_expected']);
const restoreUnchangedTarget = new Set(['failed', 'ineligible', 'rolled_back']);
// A containerlab kind shown as a short device-type label next to the node name; unknown kinds show nothing.
const restorePlatformLabels = {
 juniper_cjunosevolved: 'Junos Evolved', juniper_vjunosswitch: 'Junos', juniper_vqfx: 'Junos',
 arista_ceos: 'EOS', cisco_xrv9k: 'IOS XR'};
function restorePlatformLabel(kind) { return restorePlatformLabels[kind] || ''; }
// Preflight reasons, matched by prefix; anything unknown is shown verbatim.
const restoreReasons = [
 ['No running node in this lab matches this saved node', 'No running device in this lab has this name.'],
 ['Live restore is not supported for this platform', 'This kind of device cannot be updated this way yet.'],
 ['The saved platform does not match the running node', 'The saved configuration is for a different kind of device.'],
 ['The node is not currently running or discovery is stale', 'This device is not running, or the lab status is out of date.'],
 ['Assign NOS credentials to this node first', 'Add login credentials for this device first (Advanced › Credentials).'],
 ['Refresh VM discovery before restoring', 'Refresh the lab list (Manager ▾ › Refresh lab list), then try again.'],
 ['The node rejected the login credentials', 'The device rejected the login. Check its credentials (Advanced › Credentials).'],
 ['SSH probe failed', 'The device did not answer over SSH.'],
 ['This saved configuration has no restore data for this node', 'This saved version was made before this kind of device could be restored. Save the lab again to get a restorable version.'],
 ['The saved restore data for this node is not usable', 'The saved configuration for this device is incomplete or damaged, so it was not applied.'],
 ['Another change is waiting for confirmation on this node', 'Someone else\'s configuration change is waiting for confirmation on this device. Try again when it has finished.']];
// One device's progress, step by step, derived from the job document alone (target.stage and target.timeline, epoch
// seconds), so a closed and reopened dialog or a reloaded page rebuilds exactly the same list. Devices run side by
// side and settle in any order; each row stands on its own. Every step says in words what it is at, never by colour alone.
const restoreSteps = [
 { label: 'Queued', start: 'queued' }, { label: 'Backup', start: 'backing_up', end: 'backed_up' }, { label: 'Validate', start: 'connecting' },
 { label: 'Replace (timed recovery armed)', start: 'armed' }, { label: 'Fresh connection & read-back', start: 'verifying' },
 { label: 'Confirm', start: 'confirming' }, { label: 'Done', start: 'settled' }];
// stage -> [its step, whether that step is finished at this stage, what the step says while it runs]
const restoreStageAt = {
 queued: [0, false, 'Waiting'], backing_up: [1, false, 'Backing up the current configuration'], backed_up: [1, true, ''],
 connecting: [2, false, 'Connecting'], applying: [2, false, 'The device checks and loads the saved configuration'],
 armed: [3, true, ''], verifying: [4, false, 'Reconnecting and reading back'], confirming: [5, false, 'Confirming'],
 checking: [6, false, 'Checking with a fresh backup'], replaced: [6, true, ''], matched: [6, true, '']};
// A device's final outcome from its status: [colour class, words].
const restoreOutcomes = {
 verified: ['good', 'Replaced and verified'], applied: ['good', 'Replaced'], matched: ['good', 'Already matched — no change needed'],
 applied_unverified: ['warn', 'Replaced — not verified'], verify_mismatch: ['warn', 'Replaced — differences remain'],
 ineligible: ['skip', 'Skipped'], failed: ['bad', 'Failed — not changed'],
 rolled_back: ['warn', 'Rolled back — previous configuration read back'], uncertain: ['warn', 'Uncertain — check this device'],
 interrupted: ['warn', 'Interrupted — check this device'], rollback_expected: ['warn', 'Not confirmed — the device undoes it by itself']};
let restoreWatch = null, restoreWatchTimer = null, restoreDialogJob = '', restoreLastJob = null, restorePaused = false;

function restoreRequestId() {
 const bytes = new Uint8Array(16); crypto.getRandomValues(bytes);
 return Array.from(bytes, n => n.toString(16).padStart(2, '0')).join('');
}
function restoreBadge(status, labels) {
 const cls = ['succeeded', 'verified', 'applied'].includes(status) ? 'good'
  : restoreActiveJob.has(status) ? 'running'
  : ['failed', 'preflight_failed', 'rolled_back'].includes(status) ? 'bad' : 'warn';
 return `<span class="badge ${cls}">${esc(labels[status] || status)}</span>`;
}
// The student-facing name of an exact snapshot path: without its wire-form leading slash, without a
// trailing /latest (the legacy parent convenience), and in words for the repository root (sent as '/'
// on the wire, '' once the leading slash is stripped).
function restoreDisplayFolder(path) {
 const value = String(path || '').replace(/^\/+/, '');
 if (value === '') return 'the repository root';
 return value.replace(/\/latest$/, '');
}
function restoreSourceLabel(source) {
 if (!source) return 'Saved configuration';
 if (source.type === 'git') return 'Saved version · ' + (String(source.commit || '').slice(0, 10) || source.path || '');
 if (source.type === 'folder') return 'Saved version · ' + restoreDisplayFolder(source.path);
 if (source.type === 'backup') return 'Backup · ' + String(source.backup_job_id || '').slice(0, 10);
 return 'Saved configuration';
}
function restoreReasonLabel(reason) {
 const text = String(reason || '');
 const match = restoreReasons.find(([prefix]) => text.startsWith(prefix));
 return match ? match[1] : text;
}
// Why a device was not changed, shown beside it (not only under Details): the manager's sentence without its
// fixed lead-in. Drivers and the service word these for the student; nothing of the device's output is in them.
function restoreNotChangedReason(message) {
 return String(message || '').replace(/^Configuration was not changed[.:]\s*/, '').replace(/^Connectivity: .*/, 'The device did not answer over SSH.');
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
 // A device that undid the change was changed for a while: it is not "not changed".
 const undone = targets.filter(t => t.status === 'rolled_back').length;
 const unchanged = targets.filter(t => restoreUnchangedTarget.has(t.status)).length - undone;
 const plural = n => n === 1 ? 'device' : 'devices';
 const parts = [`Configuration replaced on ${replaced} ${plural(replaced)}.`];
 if (attention) parts.push(`${attention} ${plural(attention)} need${attention === 1 ? 's' : ''} attention.`);
 if (undone) parts.push(`${undone} ${plural(undone)} undid the change; ${undone === 1 ? 'its' : 'their'} previous configuration is back.`);
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

// Entry point from the folder browser and the Saved versions list: apply the exact snapshot folder
// to the running lab directly, without pointing the lab at that folder first. snapshotPath is the
// exact repository-relative snapshot folder (never appended with /latest), with or without its
// wire-form leading slash; '' or '/' is the repository root. Exactly one leading slash is sent on
// the wire ('/' for the root); nothing is chosen when snapshotPath is null/undefined.
async function restoreFromFolder(labId, snapshotPath, tree) {
 if (snapshotPath == null) { notify('Choose a saved folder to apply.'); return; }
 const bare = String(snapshotPath).replace(/^\/+/, '').replace(/\/+$/, '');
 const wire = '/' + bare;
 const displayFolder = restoreDisplayFolder(wire);
 const repoName = tree && tree.repository && typeof gitRepoName === 'function' ? gitRepoName(tree.repository) : '';
 const friendly = typeof savedVersionName === 'function' ? savedVersionName(displayFolder) : displayFolder;
 // The label is for the student: it never shows the wire form's leading slash.
 const where = repoName ? repoName + (bare ? ' › ' + bare : '') : bare;
 await restoreReview(labId, { type: 'folder', path: wire }, friendly + ' · ' + where);
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
  const platform = restorePlatformLabel(r.platform);
  return `<div class="restore-target-item"><label class="checkbox-label restore-target ${r.eligible ? '' : 'disabled'}">
   <input type="checkbox" name="restore-node" value="${esc(r.name)}" ${r.eligible ? 'checked' : 'disabled'}>
   <span><strong>${esc(r.short_name || r.name)}</strong>${platform ? ` <span class="caption">${esc(platform)}</span>` : ''} <small>${esc(detail)}</small></span></label>${restoreDiffDetails(r)}</div>`;
 };
 const savedAt = review.source?.captured_at ? restoreWhen(review.source.captured_at) : '';
 // Review-to-submit consistency (rule 6): a folder source pins the commit the preflight read at HEAD
 // (or the one it was asked to read), so the submitted request applies exactly what was reviewed.
 const submitSource = source.type === 'folder' ? { type: 'folder', path: source.path, commit: review.source?.commit } : source;
 const commitLabel = (source.type === 'folder' || source.type === 'git') && review.source?.commit
  ? ` <span class="caption mono">· ${esc(String(review.source.commit).slice(0, 10))}</span>` : '';
 dialog.innerHTML = `<div class="dialog-head"><h2>Replace running configuration</h2><button class="icon-button" data-op-close aria-label="Close">×</button></div>
 <p>Lab: <strong>${esc((state.labs || []).find(l => l.id === labId)?.name || '')}</strong></p>
 <p>Source: <strong>${esc(label || restoreSourceLabel(review.source))}</strong>${savedAt ? ` <span class="caption" title="${esc(utcDisplay(review.source.captured_at))}">· saved ${esc(savedAt)}</span>` : ''}${commitLabel}</p>
 <p>Current configurations are backed up first. The devices are not rebooted.</p>
 <fieldset class="restore-targets"><legend>Devices</legend>${rows.map(targetRow).join('') || '<p>None of the devices in this saved configuration are running in this lab.</p>'}</fieldset>
 ${skipped.length ? `<details class="caption"><summary>Details</summary><ul>${skipped.map(r => `<li><strong>${esc(r.short_name || r.name)}</strong>: ${esc(r.reason)}</li>`).join('')}</ul></details>` : ''}
 <ul class="restore-safety">
  <li>Each device's current configuration is backed up first. A device whose backup fails is left unchanged.</li>
  <li>The devices are not rebooted. The device itself checks the new configuration when it is activated, and the change is undone on its own if the device cannot be reached again within <span id="restore-minutes-text">${confirmDefault}</span> minutes.</li>
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
   { request_id: requestId, source: submitSource, node_names: chosen, confirm_minutes: minutes, acknowledge: true });
  dialog.close();
  await restoreShowJob(job.id, job); await refresh();
 });
}

function restoreDuration(seconds) {
 const value = Math.max(0, Math.round(Number(seconds) || 0));
 return value < 60 ? value + ' s' : Math.floor(value / 60) + ' min ' + (value % 60) + ' s';
}
function restoreTargetOutcome(t) {
 if (t.status === 'applied' && t.stage === 'checking') return null;   // replaced; the follow-up check still runs
 if (t.status === 'verified' && t.stage === 'matched') return restoreOutcomes.matched;
 if (t.status === 'applied' && t.stage === 'matched') return restoreOutcomes.matched;
 return restoreOutcomes[t.status] || null;
}
// The steps of one device: [{label, state, text, elapsed}]. state is done, current, waiting, stopped, unreached, or
// outcome-good / outcome-warn / outcome-bad / outcome-skip on the last step. null for a job stored before stages existed.
function restoreStageSteps(t, now) {
 if (!t || !t.stage) return null;
 const timeline = t.timeline || {}, at = restoreStageAt[t.stage], outcome = restoreTargetOutcome(t);
 const replaced = outcome && ['verified', 'applied', 'applied_unverified', 'verify_mismatch'].includes(t.status);
 let reached = at ? at[0] : 0;
 restoreSteps.forEach((step, i) => { if (i < 6 && timeline[step.start] != null) reached = Math.max(reached, i); });
 if (t.status === 'ineligible') reached = 0;
 const startOf = i => timeline[restoreSteps[i].start];
 const endOf = i => { for (let j = i + 1; j < restoreSteps.length; j++) if (startOf(j) != null) return startOf(j); return null; };
 const elapsed = (i, running) => {
  if (i === 3 || startOf(i) == null) return '';
  if (i === 6) return timeline.queued != null && (timeline.checked || timeline.settled) ? 'total ' + restoreDuration((timeline.checked || timeline.settled) - timeline.queued) : '';
  const end = running ? now : timeline[restoreSteps[i].end] ?? endOf(i);
  return end != null ? restoreDuration(end - startOf(i)) : '';
 };
 return restoreSteps.map((step, i) => {
  const row = { label: step.label, state: 'waiting', text: 'Waiting', elapsed: '' };
  if (i === 6) {
   if (outcome) Object.assign(row, { state: 'outcome-' + outcome[0], text: outcome[1], elapsed: elapsed(6, false) });
   else if (t.stage === 'checking') Object.assign(row, { state: 'current', text: at[2], elapsed: timeline.checking != null ? restoreDuration(now - timeline.checking) : '' });
   return row;
  }
  if (outcome && !replaced) {
   // Stopped before the end: what ran is done, the step it stopped at says so, the rest was never reached.
   if (t.status === 'ineligible') Object.assign(row, i === 0 ? { state: 'done', text: 'Done' } : { state: 'unreached', text: 'Not reached' });
   else if (i < reached) Object.assign(row, { state: 'done', text: 'Done', elapsed: elapsed(i, false) });
   else if (i === reached) Object.assign(row, { state: 'stopped', text: 'Stopped here', elapsed: elapsed(i, false) });
   else Object.assign(row, { state: 'unreached', text: 'Not reached' });
   return row;
  }
  const index = outcome ? 6 : at ? at[0] : 0, finished = outcome ? true : at ? at[1] : false;
  if (i < index || (i === index && finished)) Object.assign(row, { state: 'done', text: i === 3 ? (t.no_op ? 'Armed — no change needed' : 'Armed') : 'Done', elapsed: elapsed(i, false) });
  else if (i === index && t.stage === 'queued') Object.assign(row, { state: 'waiting', text: 'Waiting' });
  else if (i === index) Object.assign(row, { state: 'current', text: at[2] + (i === 4 && t.attempts > 1 ? ' (attempt ' + t.attempts + ')' : ''), elapsed: elapsed(i, true) });
  return row;
 });
}
function restoreStageList(t, now) {
 const steps = restoreStageSteps(t, now);
 if (!steps) return '';
 return `<ol class="restore-stage-list" aria-label="${esc('Progress of ' + (t.short_name || t.name))}">${steps.map(s =>
  `<li class="restore-stage restore-stage--${esc(s.state)}"><span class="restore-stage-glyph" aria-hidden="true"></span><span class="restore-stage-name">${esc(s.label)}</span> <span class="restore-stage-text">${esc(s.text)}</span>${s.elapsed ? ` <span class="restore-stage-time">${esc(s.elapsed)}</span>` : ''}</li>`).join('')}</ol>`;
}
// "Now" for elapsed times is the manager's clock, never the browser's: the job's server_time (sent with every
// poll), else the latest time recorded anywhere in the job. A browser clock that is off cannot distort a step.
function restoreJobNow(job) {
 if (job && Number.isFinite(Number(job.server_time)) && job.server_time) return Number(job.server_time);
 let latest = 0;
 for (const t of (job && job.targets) || []) for (const value of Object.values(t.timeline || {})) if (Number(value) > latest) latest = Number(value);
 return latest;
}
function restoreProgressLine(job) {
 const progress = job && job.progress;
 if (!progress || !progress.total) return '';
 return `<p class="restore-progress" role="status">${esc(progress.settled || 0)} of ${esc(progress.total)} ${progress.total === 1 ? 'device' : 'devices'} settled</p>`;
}
// The review's "saved → running now" diff of one device, before anything is submitted. It compares the saved
// configuration with what the device runs right now (not two saved versions); secrets are cut by the manager.
function restoreDiffFallback(diff, labels) {
 const mark = { add: '+', del: '-', context: ' ' };
 const line = l => { const type = mark[l.type] ? l.type : 'context'; return `<span class="restore-diff-${type}">${esc(mark[type] + ' ' + (l.text ?? ''))}</span>`; };
 return `<pre class="restore-diff-text"><span class="restore-diff-head">${esc('--- ' + labels.oldLabel + '\n+++ ' + labels.newLabel)}</span>\n${(diff.hunks || []).map(h =>
  esc(`@@ -${h.old_start},${h.old_count} +${h.new_start},${h.new_count} @@`) + '\n' + (h.lines || []).map(line).join('\n')).join('\n')}</pre>`;
}
function restoreDiffDetails(r) {
 if (!r.eligible) return '';
 if (!r.diff) return `<p class="form-help restore-diff-none">${esc(r.diff_reason || 'The differences are not available for this device.')}</p>`;
 if (r.diff.identical) return '';
 if (!(r.diff.hunks || []).length) return `<p class="form-help restore-diff-none">${esc(r.diff.reason || 'The differences are not available for this device.')}</p>`;
 const labels = { oldLabel: r.diff.labels?.old || 'Saved', newLabel: r.diff.labels?.new || 'Running now' };
 const body = typeof diffMarkup === 'function' ? diffMarkup(r.diff, labels) : restoreDiffFallback(r.diff, labels);
 return `<details class="restore-diff"><summary>Show differences (saved → running now)</summary>
  <p class="form-help">This compares the saved configuration with what the device runs right now. Lines starting with - are saved but missing on the device; lines starting with + are on the device now and will be removed.</p>
  ${r.diff.truncated ? '<p class="form-help">The list is long; only its first part is shown.</p>' : ''}${body}</details>`;
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
// One device's row in the job dialog; pulled out so it renders the same way in tests as in the dialog.
function restoreTargetRow(t, now) {
 const platform = restorePlatformLabel(t.platform);
 return `<div class="restore-target-row">${restoreBadge(t.status, restoreTargetLabels)}
  <strong>${esc(t.short_name || t.name)}</strong>${platform ? ` <span class="caption">${esc(platform)}</span>` : ''}
  ${restoreStageList(t, Number.isFinite(now) ? now : restoreJobNow({ targets: [t] }))}
  ${t.status === 'verify_mismatch' && (t.missing_statements || t.extra_statements)
   ? `<p class="form-help">${esc(t.missing_statements || 0)} expected configuration lines are missing and ${esc(t.extra_statements || 0)} unexpected lines remain.</p>` : ''}
  ${t.status === 'rollback_expected' ? '<p class="form-help">The change was not confirmed in time. The device is set to undo it by itself; the manager has not checked that yet.</p>' : ''}
  ${t.status === 'rolled_back' ? '<p class="form-help">The device could not be confirmed in time, so it undid the change by itself. The manager checked: the previous configuration is active.</p>' : ''}
  ${t.status === 'uncertain' ? '<p class="form-help">The manager could not check this device after the change. Look at it before relying on it.</p>' : ''}
  ${t.persistence === 'not_saved' ? '<p class="form-help">Replaced, but the device did not save it as its startup configuration; a device restart would lose it.</p>' : ''}
  ${t.status === 'ineligible' && t.message ? `<p class="form-help">${esc(restoreReasonLabel(t.message))}</p>` : ''}
  ${t.status === 'failed' && t.message ? `<p class="form-help">${esc(restoreReasonLabel(restoreNotChangedReason(t.message)))}</p>` : ''}
  ${t.message ? `<details class="caption"><summary>Details</summary><p>${esc(t.message)}</p></details>` : ''}</div>`;
}
function restoreRenderJob(job) {
 if (restoreDialogJob !== job.id || !$('restore-job-dialog')?.open) return;
 restoreLastJob = job;
 const heading = $('restore-job-dialog').querySelector('h2'); if (heading) heading.textContent = restoreJobTitle(job);
 const backupLink = (id, label) => id ? `<dt>${label}</dt><dd><button type="button" class="link-button mono" data-restore-backup="${esc(id)}">${esc(id.slice(0, 12))}</button></dd>` : '';
 $('restore-job-detail').innerHTML = `<div class="git-job-summary">${restoreBadge(job.status, restoreJobLabels)}<p>${esc(restoreResultSentence(job))}</p></div>
  ${restoreProgressLine(job)}<div class="restore-targets-status">${(job.targets || []).map(t => restoreTargetRow(t, restoreJobNow(job))).join('')}</div>
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
