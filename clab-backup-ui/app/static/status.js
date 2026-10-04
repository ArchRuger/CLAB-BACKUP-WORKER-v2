'use strict';
// Student-facing status vocabulary. Pure functions over the /api/state document: they translate the
// backend's state machines (deployment status, NOS readiness, Git job status, operations) into the
// small set of words the UI uses everywhere. Lab: Stopped / Starting / Running / Needs attention.
// Device: Starting / Ready / Unavailable / Needs attention / Needs credentials.
// Saves: the header chip's words (saveChipState): Not saved yet / Saving… / Saved / n saves to upload / Upload failed / Can't save.
// Save chip (saveChipState, loadState and the wording helpers at the end of this file): Saved / Saving / N saves to upload / Upload failed /
// Can’t save / Not saved yet / Loading / Running <name> / Loaded n of m. They are the one place that decides a chip state, a count or a name.
// Pills are ok | warn | danger | neutral | busy (busy = something is in progress right now).
// "Devices", never "routers"; "Not connected" is reserved for the VM. Nothing here touches the DOM,
// so the harness tests call these functions directly. operations.js keeps its own imperative table.
const STATUS_OPERATION_LABELS={deploy:'Starting lab',redeploy:'Redeploying lab',destroy:'Destroying lab',start:'Starting devices',stop:'Stopping devices',restart:'Restarting all devices','restart-node':'Restarting device',apply:'Updating the lab from its topology file',save:'Saving device configurations',inspect:'Checking lab status','inspect-all':'Checking running labs',create:'Creating topology file',delete:'Deleting topology file',clone:'Downloading lab files'};
const STATUS_OPERATION_BUSY=['queued','running'];
const STATUS_OPERATION_FAILED=['failed','interrupted'];
const STATUS_GIT_BUSY=['queued','capturing','exporting','pushing'];
const STATUS_RESTORE_BUSY=['queued','preflight','backing_up','applying','confirming','verifying'];
const STATUS_RESTORE_FAILED=['failed','preflight_failed','interrupted'];
// Finished, but the lab-level state needs a human look: a device whose state could not be established
// (needs_attention, which also covers a run that stopped on an unexpected error, so the wording does not claim it finished) or only some devices replaced (partial). Not "did not finish", so they get their own headline.
const STATUS_RESTORE_ATTENTION=['needs_attention','partial'];
const STATUS_RESTORE_ATTENTION_DETAIL={needs_attention:'The load needs a check on some devices.',partial:'The load finished on some devices only.'};
// After a manager restart an interrupted job may still be reading back the devices it was changing (a device can run a change
// it is about to undo by itself), and until then the manager refuses work on the lab (409; 400 for backups): it queues nothing,
// so the student starts it again afterwards. A restore's public job says so with `rechecking: true` (restore.public_job). A
// design apply's public job carries the list of devices still being read back under `rechecking` (design_apply.public_job) and no
// such key otherwise.
// Older managers send neither: not rechecking. A restore's read-back holds backups and configuration changes of its lab and
// Git saves and lab operations of every lab; a design apply's holds its own lab only (lab_operations.operation_busy).
const STATUS_RECHECK_LABEL='Checking devices';
const STATUS_RESTORE_RECHECK_DETAIL='The manager restarted while it was replacing configuration and is reading back the devices it was changing. Backups and configuration changes on this lab, and Git saves and lab operations on every lab, cannot be started until it has finished.';
const STATUS_DESIGN_RECHECK_DETAIL='The manager restarted while it was applying a network design and is reading back the devices it was changing. Backups and configuration changes on this lab cannot be started until it has finished.';
function statusRestoreRechecking(job){return job?.status==='interrupted'&&job.rechecking===true;}
function statusRestoreActive(job){return STATUS_RESTORE_BUSY.includes(job?.status)||statusRestoreRechecking(job);}
function statusDesignRechecking(job){return job?.status==='interrupted'&&Array.isArray(job.rechecking)&&job.rechecking.length>0;}
// `booting` is a Test login whose SSH login was accepted while the CLI has not answered yet: the device panel's "Starting";
// `checking` is a Test login or Test logins still running (node_services stores it meanwhile): the device panel's "Testing login…".
const STATUS_BADGE_LABELS={reachable:'Login OK',unreachable:'Login failed',booting:'Starting',checking:'Testing login…',succeeded:'Succeeded',failed:'Failed',interrupted:'Interrupted',partial:'Partly succeeded',queued:'Queued',running:'Running',Ready:'Ready'};
function plural(count,word,pluralWord){const n=Number(count)||0;return n+' '+(n===1?word:(pluralWord||word+'s'));}
// Restart device names its one device when the job is at hand ("Restarting ceos"); the table's word otherwise.
function operationLabel(action,job){if(action==='restart-node'&&job?.node_label)return 'Restarting '+job.node_label;return STATUS_OPERATION_LABELS[action]||'Lab operation';}
function statusDeviceName(node){return node?.short_name||node?.definition_node||node?.name||'This device';}
// Timestamps arrive as ISO strings (manager jobs) or Unix seconds (Git); both become epoch ms, invalid → 0.
function statusEpoch(value){if(!value)return 0;const time=typeof value==='number'?value*(value<1e12?1000:1):new Date(value).getTime();return Number.isNaN(time)?0:time;}
function statusJobTime(job){return statusEpoch(job?.finished)||statusEpoch(job?.created);}
// The host name of a Git push URL ("github.com"); https, ssh:// and scp-like forms are all accepted.
function statusHost(url){const text=String(url||'');const m=text.match(/^[a-z][a-z0-9+.-]*:\/\/(?:[^@/]+@)?([^:/?#]+)/i)||text.match(/^[^@/]+@([^:/]+)[:/]/);return m?m[1].toLowerCase():'';}
// Per-node predicates shared by labState, deviceState and credentialsNeeded so every count agrees.
function statusNotRunning(node){return !node?.ssh_ready&&(node?.available===false||node?.nos_login?.status==='unavailable');}
function statusNeedsCredentials(node){
 if(!node||node.ssh_ready||statusNotRunning(node))return false;const login=node.nos_login?.status;
 if(login==='booting'||login==='failed'||login==='ready')return false;
 return login==='needs_credentials'||node.readiness==='Needs credentials'||node.login_configured===false;
}
// "12 minutes ago" for recent times; dates further away read as a calendar date so nobody has to
// count days. Invalid or missing timestamps read as an empty string, never "NaN minutes ago".
function relativeTime(value,now){
 const time=statusEpoch(value);if(!time)return '';
 const reference=now===undefined?Date.now():now,diff=Math.max(0,reference-time),minute=60000,hour=3600000,day=86400000;
 if(diff<45000)return 'just now';if(diff<hour)return plural(Math.round(diff/minute),'minute')+' ago';
 if(diff<day)return plural(Math.round(diff/hour),'hour')+' ago';if(diff<day*2)return 'yesterday';
 if(diff<day*7)return plural(Math.round(diff/day),'day')+' ago';
 return new Date(time).toLocaleDateString(undefined,{year:'numeric',month:'short',day:'numeric'});
}
// Latest activity for a lab across the job collections; ctx is the /api/state document.
function labActivity(lab,ctx={}){
 const mine=job=>job&&job.lab_id===lab?.id;
 const operation=(ctx.operations||[]).find(j=>STATUS_OPERATION_BUSY.includes(j.status)&&mine(j));
 const restore=(ctx.restore_jobs||[]).find(j=>STATUS_RESTORE_BUSY.includes(j.status)&&mine(j))||(ctx.restore_jobs||[]).find(j=>statusRestoreRechecking(j)&&mine(j));
 const design=(ctx.design_jobs||[]).find(j=>statusDesignRechecking(j)&&mine(j));
 const save=(ctx.git_jobs||[]).find(j=>STATUS_GIT_BUSY.includes(j.status)&&mine(j));
 const backup=(ctx.jobs||[]).find(j=>STATUS_OPERATION_BUSY.includes(j.status)&&mine(j));
 return {operation,restore,design,save,backup};
}
// The newest finished operation or restore job of the lab, when it ended badly and the student has
// not dismissed it (ctx.dismissed is a Set of job ids). A later job that finished cleanly clears it,
// so "Try again" succeeding never leaves a stale warning behind.
function labFailure(lab,ctx={}){
 const dismissed=ctx.dismissed,isDismissed=id=>!!dismissed&&(typeof dismissed.has==='function'?dismissed.has(id):Array.isArray(dismissed)&&dismissed.includes(id));
 const done=[];
 for(const j of ctx.operations||[])if(j.lab_id===lab?.id&&!STATUS_OPERATION_BUSY.includes(j.status))done.push({job:j,failed:STATUS_OPERATION_FAILED.includes(j.status),label:operationLabel(j.action)});
 for(const j of ctx.restore_jobs||[])if(j.lab_id===lab?.id&&!statusRestoreActive(j))done.push({job:j,failed:STATUS_RESTORE_FAILED.includes(j.status)||STATUS_RESTORE_ATTENTION.includes(j.status),label:'Loading a saved state',...(STATUS_RESTORE_ATTENTION.includes(j.status)?{detail:STATUS_RESTORE_ATTENTION_DETAIL[j.status],pill:'warn'}:{})});
 const newest=done.sort((a,b)=>statusJobTime(b.job)-statusJobTime(a.job))[0];
 return newest&&newest.failed&&!isDismissed(newest.job.id)?newest:null;
}
// Lab state → {key,label,detail,ready,total,pill,job?}. Priority: something in progress, then a job
// that did not finish, then discovery problems, then the deployment state, then NOS readiness.
// ready/total count every device of the lab, so devices without credentials never vanish.
function labState(lab,ctx={}){
 if(!lab)return {key:'unknown',label:'Unknown',detail:'',ready:0,total:0,pill:'neutral'};
 const nodes=lab.nodes||[],readiness=lab.nos_readiness||{},total=nodes.length,ready=nodes.filter(n=>n.ssh_ready).length;
 const credentials=credentialsNeeded(lab),notRunning=nodes.filter(statusNotRunning).length;
 const readyText=`${ready} of ${total} devices ready`+(credentials?` · ${credentials} ${credentials===1?'needs':'need'} login credentials`:'')+(notRunning?` · ${notRunning} not running`:'');
 const activity=labActivity(lab,ctx);
 if(activity.operation)return {key:'working',label:operationLabel(activity.operation.action,activity.operation),detail:activity.operation.message||'Running on the lab VM.',ready,total,pill:'busy',job:activity.operation};
 if(activity.restore&&statusRestoreRechecking(activity.restore))return {key:'working',label:STATUS_RECHECK_LABEL,detail:STATUS_RESTORE_RECHECK_DETAIL,ready,total,pill:'busy',job:activity.restore};
 if(activity.restore)return {key:'working',label:'Loading a saved state',detail:activity.restore.message||'Applying a saved configuration.',ready,total,pill:'busy',job:activity.restore};
 if(activity.design)return {key:'working',label:STATUS_RECHECK_LABEL,detail:STATUS_DESIGN_RECHECK_DETAIL,ready,total,pill:'busy',job:activity.design};
 const failure=labFailure(lab,ctx);
 if(failure)return {key:'attention',label:'Needs attention',detail:failure.detail||`${failure.label} did not finish.`,ready,total,pill:failure.pill||'danger',job:failure.job};
 const status=lab.deployment?.status||'Unlinked';
 if(status==='Unlinked')return {key:'unlinked',label:'Not matched to a running lab',detail:'The manager cannot tell which lab on the VM this is.',ready,total,pill:'neutral'};
 if(status==='Unknown')return {key:'unknown',label:'Status unknown',detail:ctx.discovery?.configured===false?'Connect the lab VM to see whether this lab is running.':'The lab VM cannot be reached right now, so this status may be out of date.',ready,total,pill:'neutral'};
 if(status==='Not deployed'||status==='Stopped')return {key:'stopped',label:'Stopped',detail:'The lab is not running.',ready,total,pill:'neutral'};
 if(status==='Partially running'){const running=nodes.filter(n=>n.runtime_state==='running').length;return {key:'attention',label:'Some devices stopped',detail:`${running} of ${total} devices are running.`,ready,total,pill:'warn'};}
 if(status==='Running'){
  if(readiness.status==='booting')return {key:'starting',label:'Starting',detail:readyText+'. SSH becomes available automatically.',ready,total,pill:'warn'};
  if(readiness.status==='failed')return {key:'attention',label:'Needs attention',detail:`SSH login failed on ${plural(readiness.failed||0,'device')}. ${readyText}.`,ready,total,pill:'danger'};
  return {key:'running',label:'Running',detail:readyText,ready,total,pill:'ok'};
 }
 return {key:'unknown',label:String(status),detail:lab.deployment?.message||'',ready,total,pill:'neutral'};
}
// Device state → {key,label,detail,next,cli,pill}. `detail` is a full sentence naming the device;
// `next` is the action the student can take; `cli` says whether Open CLI works right now.
function deviceState(node){
 const name=statusDeviceName(node),login=node?.nos_login?.status;
 if(!node)return {key:'unknown',label:'Unknown',detail:'',next:'',cli:false,pill:'neutral'};
 // Restart device is running for this one device (the server says so while its job is queued or running):
 // it is neither ready nor merely booting, whatever the container state of the moment says.
 if(login==='restarting')return {key:'working',label:'Restarting',detail:`${name} is restarting on the VM. Its CLI opens again once it accepts a login.`,next:'',cli:false,pill:'busy'};
 if(node.ssh_ready)return {key:'ready',label:'Ready',detail:login==='unmonitored'?'Connected with the saved address.':`${name} is accepting SSH logins.`,next:'',cli:true,pill:'ok'};
 if(statusNotRunning(node))return {key:'unavailable',label:'Unavailable',detail:`${name} is not running, or the lab status is out of date.`,next:'Start lab',cli:false,pill:'neutral'};
 // A refresh (Test logins, or this device's own Test login) is answering right now; only a
 // real answer ever marks a device ready, so this is never optimistic.
 if(login==='checking')return {key:'testing',label:'Testing login…',detail:`Testing the SSH login of ${name} again.`,next:'',cli:false,pill:'busy'};
 if(login==='booting')return {key:'starting',label:'Starting',detail:`${name} is still starting. SSH opens automatically when it answers. Use Test logins (above) or this device's Test login (in its panel, under Advanced) to check again now.`,next:'',cli:false,pill:'warn'};
 if(login==='failed')return {key:'attention',label:'Needs attention',detail:`${name} is running, but SSH login failed with the saved credentials.`,next:'Check credentials',cli:false,pill:'danger'};
 if(statusNeedsCredentials(node))return {key:'credentials',label:'Needs credentials',detail:`Add login credentials to open the CLI of ${name}. Add them under Devices, then use Test logins to check again.`,next:'Add credentials',cli:false,pill:'warn'};
 if(!node.platform||node.readiness==='Choose NOS')return {key:'credentials',label:'Choose network OS',detail:`Tell the manager which network OS ${name} runs.`,next:'Edit connection',cli:false,pill:'warn'};
 return {key:'unknown',label:'Unknown',detail:'',next:'',cli:false,pill:'neutral'};
}
// How many devices of the lab cannot open a CLI until login credentials are added.
function credentialsNeeded(lab){return (lab?.nodes||[]).filter(statusNeedsCredentials).length;}
// The lab's Git jobs, newest first, without repository update markers (the save chip reads them: saveChipState below).
function statusLabGitJobs(lab,gitJobs){return (gitJobs||[]).filter(j=>j.lab_id===lab?.id&&j.target!=='update').sort((a,b)=>String(b.created||'').localeCompare(String(a.created||'')));}
// Backup / login-check badges in the technical table and job list; unknown values pass through and
// the caller keeps the raw value in `title`.
function badgeLabel(status){return STATUS_BADGE_LABELS[status]||String(status??'');}
// A student-facing name for a saved state, from its folder (DESIGN.md 3.8, the states route follows the same rule): the last folder
// name once a trailing `latest` is dropped, its first letter upper-cased when the name is all lower case ("start" → "Start",
// "broken-2" → "Broken-2", "BGP" and "Final" unchanged). The top level has no name: '' (callers say "the repository's top level").
function savedVersionName(folder){
 const parts=String(folder||'').split('/').filter(Boolean);
 if(parts[parts.length-1]==='latest')parts.pop();
 const name=parts.pop()||'';
 return name&&name===name.toLowerCase()?name.charAt(0).toUpperCase()+name.slice(1):name;
}

// Where uploads of a repository go, for the place being chosen: `Uploads go to github.com/owner/repository, branch main.` from the
// repository's address without credentials (the manager strips them) and its branch. '' when the address is not known.
function saveUploadsText(remote,branch){
 const text=String(remote||'').trim().replace(/^[a-z][a-z0-9+.-]*:\/\/(?:[^@/]+@)?/i,'').replace(/^[^@/]+@([^:/]+):/,'$1/').replace(/\.git$/,'').replace(/\/+$/,'');
 return text?`Uploads go to ${text}${branch?', branch '+branch:''}.`:'';
}
// ---- The save chip and the load state (DESIGN.md 7.1) -------------------------------------------------------------------------
// saveChipState and loadState are the only code that decides a chip state, a count or a name; the header, its panels, the
// drawers and the home card all read them. Every function here is pure over the /api/state document.
const STATUS_SAVE_WAITING=['committed','review_pending','push_pending','interrupted'];
const STATUS_SAVE_STOPPED=['export_pending','capture_incomplete','failed'];
const STATUS_SAVE_CAPTURED=['synced','unchanged','committed','review_pending','push_pending'];
const STATUS_LOAD_REPLACED=['verified','applied','applied_unverified','verify_mismatch'];
const STATUS_LOAD_ENDERS=['deploy','redeploy','destroy'];
const STATUS_PROBLEM_CODES=['vm','account','busy','diverged','files','settings','devices','other'];
// A device's words in a load (LOAD.md 5.1), keyed by the restore service's target status; `matched` is a verified or applied device
// whose stage is `matched`. The only mapping from an outcome to words. `help` sits under the device's name.
const STATUS_LOAD_WORDS={
 verified:{text:'Loaded',cls:'ok',help:''},
 matched:{text:'Already matched',cls:'ok',help:''},
 applied:{text:'Loaded',cls:'ok',help:''},
 applied_unverified:{text:'Loaded, not verified',cls:'warn',help:''},
 verify_mismatch:{text:'Loaded, differences remain',cls:'warn',help:''},
 failed:{text:'Not loaded',cls:'bad',help:''},
 ineligible:{text:'Skipped',cls:'',help:''},
 rolled_back:{text:'Kept previous',cls:'bad',help:'Undid the change; its previous configuration was read back.'},
 uncertain:{text:'Not confirmed',cls:'warn',help:'The manager could not confirm what this device runs. Open Details.'},
 interrupted:{text:'Interrupted',cls:'warn',help:'Open Details.'},
 rollback_expected:{text:'Not confirmed',cls:'warn',help:'Open Details.'}};
// Words for a device that has no final word yet.
const STATUS_LOAD_PROGRESS={waiting:{text:'Waiting',cls:''},backing_up:{text:'Backing up…',cls:'now'},loading:{text:'Loading…',cls:'now'},checking:{text:'Checking…',cls:'now'}};
const STATUS_LOAD_RUNNING_STATUS=['pending','backing_up','applying','confirming'];
const STATUS_MONTHS=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
// 'just now' | '21 min ago' | '2 h ago' | 'yesterday' | '3 days ago' | '12 Sep' (the year is added after about ten months). Invalid → ''.
function relativeTimeShort(value,now){
 const time=statusEpoch(value);if(!time)return '';
 const reference=now===undefined?Date.now():now,diff=Math.max(0,reference-time),minute=60000,hour=3600000,day=86400000;
 if(diff<45000)return 'just now';if(diff<hour)return Math.min(59,Math.max(1,Math.round(diff/minute)))+' min ago';
 if(diff<day)return Math.min(23,Math.max(1,Math.round(diff/hour)))+' h ago';if(diff<day*2)return 'yesterday';
 if(diff<day*7)return plural(Math.min(6,Math.round(diff/day)),'day')+' ago';
 const date=new Date(time);return date.getDate()+' '+STATUS_MONTHS[date.getMonth()]+(diff>=day*300?' '+date.getFullYear():'');
}
// The lab's Git jobs, newest first, without repository updates and without saves the person put aside.
function statusSaveJobs(lab,ctx){return statusLabGitJobs(lab,ctx?.git_jobs).filter(j=>j.status!=='dismissed');}
function statusOwnKind(job){return job.kind!=='state'&&job.kind!=='design';}
// S of DESIGN.md 7.1: the lab's save jobs that read the devices themselves, newest first. A job stored before `captured` existed counts
// when it wrote `latest`; a checkpoint or starting point made from an existing capture (captured false) is not one.
// The time of S is when the save read the devices: its creation (the capture follows at once). `finished` is not that time: it moves
// again when the save is uploaded, which may be long after a load, and an upload must never end Running or reorder the saves.
function statusSaveTime(job){return statusEpoch(job?.created)||statusEpoch(job?.finished);}
function statusCaptureSaves(lab,ctx){
 return statusSaveJobs(lab,ctx).filter(j=>statusOwnKind(j)&&STATUS_SAVE_CAPTURED.includes(j.status)&&(j.captured===undefined?j.target==='latest':j.captured===true)).sort((a,b)=>statusSaveTime(b)-statusSaveTime(a));
}
// Jobs with a commit that is not uploaded. A lab state, a design export and a folder move are in it; the lab need not be connected.
function statusWaitingSaves(lab,ctx){return statusSaveJobs(lab,ctx).filter(j=>j.commit&&!j.pushed&&STATUS_SAVE_WAITING.includes(j.status));}
// A device is unknown only when its stage is `uncertain` or it still awaits its read-back (interrupted, timeline not settled). One interrupted
// before it was changed is settled as failed at start-up and is not unknown; a job stored before stages existed has no timeline.
function statusLoadUnknown(t){return t?.status==='uncertain'||t?.stage==='uncertain'||(t?.status==='interrupted'&&!!t.timeline&&t.timeline.settled==null);}
function statusLoadEffective(job){return !!job&&!statusRestoreActive(job)&&(job.targets||[]).some(t=>STATUS_LOAD_REPLACED.includes(t.status)||statusLoadUnknown(t));}
function statusNotChangedReason(message){return String(message||'').replace(/^Configuration was not changed[.:]\s*/,'').replace(/^Connectivity: .*/,'The device did not answer over SSH.');}
// One device of a load → {text, cls, final, help}. `final` says the text is the device's outcome (the chip's "k of m" counts these);
// a device still being worked on reads Waiting, Backing up…, Loading… or, while the manager reads it back after a restart, Checking….
function loadDeviceWord(target,job){
 const t=target||{},status=t.status,stage=t.stage,has=Object.prototype.hasOwnProperty;
 const final=(word,help)=>({text:word.text,cls:word.cls,final:true,help:help===undefined?word.help:help}),open=word=>({text:word.text,cls:word.cls,final:false,help:''});
 if(status==='applied'&&stage==='checking')return open(STATUS_LOAD_PROGRESS.loading);   // replaced; the follow-up check still runs
 if((status==='verified'||status==='applied')&&stage==='matched')return final(STATUS_LOAD_WORDS.matched);
 if(status==='interrupted'&&job&&statusRestoreRechecking(job)&&!!t.timeline&&t.timeline.settled==null)return open(STATUS_LOAD_PROGRESS.checking);
 if(status!=='matched'&&has.call(STATUS_LOAD_WORDS,status))return final(STATUS_LOAD_WORDS[status],status==='failed'?statusNotChangedReason(t.message):undefined);
 if(STATUS_LOAD_RUNNING_STATUS.includes(status)||status===undefined){
  if(stage==='backing_up'||stage==='backed_up'||(!stage&&status==='backing_up'))return open(STATUS_LOAD_PROGRESS.backing_up);
  if(stage==='queued'||(!stage&&(status==='pending'||status===undefined)))return open(STATUS_LOAD_PROGRESS.waiting);
  return open(STATUS_LOAD_PROGRESS.loading);
 }
 return final({text:'Not confirmed',cls:'warn'},'Open Details.');   // a status this page does not know is never worded as an outcome it did not report
}
// The counts of a load job: total devices, done (devices with a final word), loaded (verified only, the chip's n), replaced, unverified
// (loaded but not verified, or differences remain), unknown (not confirmed or awaiting read-back), failed, rolledBack, skipped, interrupted, matched.
function loadCounts(job){
 const targets=(job&&job.targets)||[],c={total:targets.length,done:0,loaded:0,replaced:0,unverified:0,unknown:0,failed:0,rolledBack:0,skipped:0,interrupted:0,matched:0};
 for(const t of targets){
  if(loadDeviceWord(t,job).final)c.done+=1;
  if(t.status==='verified')c.loaded+=1;
  if(STATUS_LOAD_REPLACED.includes(t.status))c.replaced+=1;
  if(t.status==='applied_unverified'||t.status==='verify_mismatch')c.unverified+=1;
  if(statusLoadUnknown(t))c.unknown+=1;
  if(t.status==='failed')c.failed+=1;
  if(t.status==='rolled_back')c.rolledBack+=1;
  if(t.status==='ineligible')c.skipped+=1;
  if(t.status==='interrupted')c.interrupted+=1;
  if((t.status==='verified'||t.status==='applied')&&t.stage==='matched')c.matched+=1;
 }
 return c;
}
// The name of the state a load put on the devices, after "Running" (DESIGN.md 7.1). Derived, never stored, so a renamed save shows its
// current name. `lab` (default ctx.lab) gives the lab's folder; ctx.states are the rows of the saved-states list when the page holds one.
function loadSourceName(source,ctx,lab,now,depth=0){
 ctx=ctx||{};lab=lab||ctx.lab;
 const s=source||{},strip=p=>String(p||'').replace(/^\/+/,'').replace(/\/+$/,''),path=strip(s.path||s.folder);
 if(s.type==='backup'){
  const backup=(ctx.jobs||[]).find(j=>j.id===s.backup_job_id),before=backup&&backup.source==='restore-pre'?(ctx.restore_jobs||[]).find(j=>j.id===backup.progress_id):null;
  if(!before||depth>4){const when=relativeTimeShort(backup?.finished||backup?.created,now);return when?'a backup from '+when:'a backup';}
  const inner=before.source||{},innerBackup=inner.type==='backup'?(ctx.jobs||[]).find(j=>j.id===inner.backup_job_id):null,undone=innerBackup&&innerBackup.source==='restore-pre'?(ctx.restore_jobs||[]).find(j=>j.id===innerBackup.progress_id):null;
  if(undone)return loadSourceName(undone.source,ctx,lab,now,depth+1);   // the undo of an undo of X reads "X"
  return 'the configuration from before '+loadSourceName(inner,ctx,lab,now,depth+1);
 }
 const bound=!!lab?.git_binding,prefix=strip(lab?.git_binding?.repository?.prefix),own=p=>(prefix?prefix+'/':'')+p;
 const row=(ctx.states||[]).find(r=>strip(r.path)===path&&(!s.commit||!r.commit||r.commit===s.commit));
 if(bound&&path===own('latest')){
  // The save whose capture is the loaded state's (the commit cannot tell: a folder source pins the checkout's HEAD, which is another lab's save as soon as one lands).
  const capture=String(s.capture_id||''),save=capture?(ctx.git_jobs||[]).find(j=>j.lab_id===lab.id&&j.backup_job_id===capture&&statusOwnKind(j)&&(j.target||'latest')==='latest'):null;
  if(save){
   if(save.note)return save.note;
   const newest=statusCaptureSaves(lab,ctx)[0];if(newest&&newest.id===save.id)return 'your latest save';
  }
  const made=(ctx.jobs||[]).find(j=>j.id===capture),when=relativeTimeShort(row?.saved_at||made?.finished||made?.created||s.saved_at||s.captured_at,now);
  return when?'an earlier save, '+when:'an earlier save';
 }
 if(bound&&path===own('baseline'))return 'your starting point';
 if(bound&&path.startsWith(own('checkpoints/')))return path.slice(own('checkpoints/').length)||'a checkpoint';
 if(row&&row.name)return String(row.name);
 return savedVersionName(path)||'a saved state';
}
// The load part of the chip. → {key: 'loading'|'running'|'partial'|'', job, name, loaded, total, done, at, rechecking, last, undo: {available, reason}}.
// 'loading': a restore job of the lab is active (done = devices with a final word). 'running' / 'partial': the newest effective load L is newer than
// the newest capture save S and no deploy, redeploy, destroy or design apply of the lab finished after it (a succeeded load is running; any other
// is partial, `loaded` counting verified devices only). `last` is the newest effective load whether or not something ended it:
// {job, name, at, loaded, total, key} or null. `recent` is the lab's newest finished load of any kind, {job, name, at, changed}: a load
// that changed no device is no chip state, but its job window must stay one click away (the panel's Last load line reads it).
// `undo` is about `job` and says why not when its automatic backup is no longer kept.
function loadState(lab,ctx={},now){
 ctx=ctx||{};
 const empty={key:'',job:null,name:'',loaded:0,total:0,done:0,at:0,rechecking:false,last:null,recent:null,undo:{available:false,reason:''}};if(!lab)return empty;
 const mine=j=>!!j&&j.lab_id===lab.id,restores=(ctx.restore_jobs||[]).filter(mine);
 const newest=restores.filter(j=>!statusRestoreActive(j)).sort((a,b)=>statusJobTime(b)-statusJobTime(a))[0]||null;
 const recent=newest?{job:newest,name:loadSourceName(newest.source,ctx,lab,now),at:statusJobTime(newest),changed:statusLoadEffective(newest)}:null,none={...empty,recent};
 const effective=restores.filter(statusLoadEffective).sort((a,b)=>statusJobTime(b)-statusJobTime(a))[0]||null,at=effective?statusJobTime(effective):0,effectiveCounts=loadCounts(effective);
 const last=effective?{job:effective,name:loadSourceName(effective.source,ctx,lab,now),at,loaded:effectiveCounts.loaded,total:effectiveCounts.total,key:effective.status==='succeeded'?'running':'partial'}:null;
 const active=restores.filter(statusRestoreActive).sort((a,b)=>statusJobTime(b)-statusJobTime(a))[0];
 if(active){const counts=loadCounts(active);return {...none,key:'loading',job:active,name:loadSourceName(active.source,ctx,lab,now),loaded:counts.loaded,total:counts.total,done:counts.done,at:statusJobTime(active),rechecking:statusRestoreRechecking(active),last};}
 if(!effective)return none;
 const save=statusCaptureSaves(lab,ctx)[0];if(save&&statusSaveTime(save)>=at)return {...none,last};
 const ended=(ctx.operations||[]).some(j=>mine(j)&&STATUS_LOAD_ENDERS.includes(j.action)&&!STATUS_OPERATION_BUSY.includes(j.status)&&statusJobTime(j)>at)
  ||(ctx.design_jobs||[]).some(j=>mine(j)&&!STATUS_RESTORE_BUSY.includes(j.status)&&!statusDesignRechecking(j)&&statusJobTime(j)>at)
  ||statusEpoch(lab.last_deployed)>at;
 if(ended)return {...none,last};
 const kept=effective.pre_backup_job_id?(ctx.jobs||[]).some(j=>j.id===effective.pre_backup_job_id):false;
 const undo=effective.pre_backup_job_id?{available:kept,reason:kept?'':'The automatic backup of this load is no longer kept.'}:{available:false,reason:''};
 return {...none,key:last.key,job:effective,name:last.name,loaded:effectiveCounts.loaded,total:effectiveCounts.total,done:effectiveCounts.done,at,last,undo};
}
// The one chip (DESIGN.md 7.1). ctx is the /api/state document plus ctx.refusal = {message, at}, the refusal of a save this page just sent
// (page memory; a refusal without a time is the newest event) and ctx.states = the saved-states rows the page holds. Returns
// {key, dot, text, panel, detail, code, job, load, count, at, also, also2, saveDisabled, loadDisabled}:
//  key: loading saving cant partial running failed waiting saved kept none; dot: the save-dot modifier; panel: the view the chip opens
//  (loading saving cant partial running failed upload rest first); detail: the reason text of cant; code: lab.git_status.code of a cant caused
//  by the status alone, '' when a failed attempt or a refusal is the cause; job: the job the state is about; load: loadState's answer while a
//  load is active or still describes the devices; count: waiting saves (distinct commits) whichever state wins; at: the time the state refers to;
//  also / also2: {key, text, panel, job} for a hidden state (also2 only under a cant that hides a load: the waiting or failed upload).
function saveChipState(lab,ctx={},now){
 ctx=ctx||{};
 const base={key:'none',dot:'none',text:'Not saved yet',panel:'first',detail:'',code:'',job:null,load:null,count:0,at:'',also:null,also2:null,saveDisabled:false,loadDisabled:false};
 if(!lab)return base;
 const load=loadState(lab,ctx,now),bound=!!lab.git_binding,jobs=statusSaveJobs(lab,ctx),captures=statusCaptureSaves(lab,ctx),saveAt=captures[0]?statusSaveTime(captures[0]):0;
 const waiting=statusWaitingSaves(lab,ctx),count=new Set(waiting.map(j=>j.commit)).size,uploadFailed=waiting.find(j=>j.status==='push_pending');
 const live=load.key==='running'||load.key==='partial',loadAt=live?load.at:0;
 if(load.key==='loading')return {...base,key:'loading',dot:'busy',text:load.rechecking?'Checking devices…':load.total?`Loading… ${load.done} of ${load.total}`:'Loading…',panel:'loading',job:load.job,load,count,saveDisabled:true,loadDisabled:true};
 const active=(ctx.git_jobs||[]).find(j=>j.lab_id===lab.id&&STATUS_GIT_BUSY.includes(j.status));
 if(active)return {...base,key:'saving',dot:'busy',text:active.target==='update'?'Updating…':active.status==='pushing'?'Uploading…':'Saving…',panel:'saving',job:active,count,saveDisabled:true};
 // A failed attempt: the newest job ended without a result, or the page holds a refusal.
 const newest=jobs[0]||null,stopped=newest&&(STATUS_SAVE_STOPPED.includes(newest.status)||(newest.status==='interrupted'&&!newest.commit))?newest:null;
 const refusal=ctx.refusal&&ctx.refusal.message?ctx.refusal:null,failedAt=Math.max(stopped?Math.max(1,statusJobTime(stopped)):0,refusal?statusEpoch(refusal.at)||Infinity:0);
 // The status the manager remembers for the lab. A lab without a save location has one only after a placement the VM refused
 // (PROMPT 6.5): it counts when it carries a cause the page can word; any other refusal stays the first-save panel's own line.
 const status=lab.git_status||null,unready=!!status&&status.checked!==false&&status.ready===false&&(bound||(!!status.code&&status.code!=='other')),attempt=failedAt>saveAt;
 const cant=()=>({key:'cant',dot:'bad',text:'Can’t save',panel:'cant',job:stopped,detail:String(refusal?.message||(attempt&&stopped?stopped.message:'')||status?.problem||''),code:refusal||(attempt&&stopped)?'':String(status?.code||'other')});
 const states=[];
 if(attempt&&(!live||failedAt>loadAt))states.push(cant());                                                                  // row 3
 if(live)states.push(load.key==='running'?{key:'running',dot:'info',text:'Running '+load.name,panel:'running',job:load.job,at:load.job.finished||load.job.created||''}:{key:'partial',dot:'warn',text:`Loaded ${load.loaded} of ${load.total}`,panel:'partial',job:load.job,at:load.job.finished||load.job.created||''});   // rows 4, 5
 if(!states.some(s=>s.key==='cant')&&(attempt||unready))states.push(cant());                                               // row 6
 if(uploadFailed)states.push({key:'failed',dot:'bad',text:'Upload failed',panel:'failed',job:uploadFailed});                // row 7
 else if(count)states.push({key:'waiting',dot:'warn',text:plural(count,'save')+' to upload',panel:'upload',job:waiting[0]});   // row 8
 const shown=captures.find(j=>j.status!=='unchanged')||captures[0]||null;
 if(shown&&(shown.status==='synced'||shown.status==='unchanged'||shown.pushed===true)){const at=shown.finished||shown.created||'',when=relativeTimeShort(at,now);states.push({key:'saved',dot:'ok',text:when?'Saved '+when:'Saved',panel:bound?'rest':'first',job:shown,at});}   // row 9
 else{
  const own=statusLabGitJobs(lab,ctx.git_jobs).filter(j=>statusOwnKind(j)&&j.target!=='move'),kept=own.length&&own.every(j=>j.status==='dismissed')?own[0]:null;
  states.push(kept?{key:'kept',dot:'none',text:'Kept on this VM',panel:bound?'rest':'first',job:kept,at:kept.finished||kept.created||''}:{key:'none',dot:'none',text:'Not saved yet',panel:'first'});   // rows 10, 11
 }
 const top=states[0],rest=states.slice(1),upload=s=>s.key==='failed'||s.key==='waiting',alsoOf=s=>s?{key:s.key,text:s.text,panel:s.panel,job:s.job||null}:null;
 let also=null,also2=null;
 if(top.key==='cant'&&live){also=alsoOf(rest.find(s=>s.key==='running'||s.key==='partial'));also2=alsoOf(rest.find(upload));}
 else if(top.key==='cant')also=alsoOf(rest.find(upload));
 else if(live)also=alsoOf(rest.find(s=>s.key==='cant'||upload(s)));
 return {...base,load:live?load:null,count,...top,also,also2};
}
// Why a save cannot be made (the Can't save view, DESIGN.md 3.6). The cause is found in this order: a job that stopped on a device
// (capture_incomplete), then lab.git_status.code when the status is not ready, else `other`; no message text is matched.
// → {code, sentence, actions: [{action, label}], devices, commands, job, detail}; the first action is the primary one. `commands`: what the
// repository's owner runs on the VM when both sides have changes (the manager never merges); Try again then uploads the waiting saves. Codes: vm account busy diverged
// (the sentence and actions differ by whether a save waits in the repository) device capture files settings devices other. `capture`: the
// manager stopped the save for its own reason and its sentence is shown as it is. `settings`: the save
// location has to be set up again (the VM's record or checkout is gone or changed; Details shows the VM's own sentence, which says what to
// do). `devices`: the selection of Save settings holds no device of the lab. `detail` is the raw text for Details.
function saveProblem(lab,ctx={}){
 ctx=ctx||{};
 const bound=!!lab?.git_binding,status=lab?.git_status||null,unready=!!status&&status.checked!==false&&status.ready===false,jobs=statusSaveJobs(lab,ctx),newest=jobs[0]||null;
 const stopped=newest&&(STATUS_SAVE_STOPPED.includes(newest.status)||(newest.status==='interrupted'&&!newest.commit))?newest:null,refusal=ctx.refusal&&ctx.refusal.message?ctx.refusal:null;
 const capture=!!stopped&&stopped.status==='capture_incomplete'&&!(refusal&&(statusEpoch(refusal.at)||Infinity)>statusJobTime(stopped));
 // The device sentence only when the capture names a device that did not succeed, or the capture is gone. A save the manager
 // stopped for its own reason (the topology could not be saved with the capture, the capture does not hold the devices) says so
 // in the manager's own sentence.
 const captured=capture?(ctx.jobs||[]).find(j=>j.id===stopped.backup_job_id):null,device=capture&&(!captured||((captured.nodes)||[]).some(n=>n.status!=='succeeded'));
 const repository=lab?.git_binding?.repository||{},host=statusHost(repository.push_url)||'the online repository',folder=String(repository.prefix||'').replace(/^\/+|\/+$/g,'');
 const again={action:'again',label:'Try again'},details={action:'details',label:'Details'},detail=String(refusal?.message||stopped?.message||status?.problem||'');
 const checkout=repository.path||'',waits=(+status?.waiting>0)||(!!checkout&&(ctx.git_jobs||[]).some(j=>j.commit&&!j.pushed&&STATUS_SAVE_WAITING.includes(j.status)&&(j.destination?.checkout||'')===checkout));
 const list=names=>names.length<2?(names[0]||''):names.slice(0,-1).join(', ')+' and '+names[names.length-1];
 const make=(code,sentence,actions,devices=[],commands=[])=>({code,sentence,actions,devices,commands,job:stopped,detail});
 if(device){
  const backup=(ctx.jobs||[]).find(j=>j.id===stopped.backup_job_id),nodes=lab?.nodes||[];
  const devices=((backup&&backup.nodes)||[]).filter(n=>n.status!=='succeeded').map(n=>{const node=nodes.find(x=>x.name===n.name);return n.short_name||node?.short_name||statusDeviceName(node||{name:n.name});});
  return make('device',devices.length?`${list(devices)} could not be read, so nothing was saved.`:'A device could not be read, so nothing was saved.',[again,{action:'settings',label:'Save settings'},details],devices);
 }
 if(capture)return make('capture',String(stopped.message||'The save did not work.'),[again,details]);
 const code=unready&&STATUS_PROBLEM_CODES.includes(status.code)?status.code:'other';
 if(code==='vm')return make('vm','The lab VM could not be reached.',[again,{action:'vm',label:'Check the VM connection…'}]);
 if(code==='account')return make('account',`The VM account cannot upload to ${host}.`,[again,details]);
 if(code==='busy')return make('busy','Someone is working in this repository on the VM.',[again,details]);
 if(code==='diverged')return waits?make('diverged','The online copy and this VM both have changes the other does not have. They have to be combined on the VM.',[{action:'upload-again',label:'Try again'},details],[],checkout?[`git -C ${checkout} pull --no-rebase`,`git -C ${checkout} push`]:[]):make('diverged','The online copy has changes this VM does not have.',[{action:'update',label:'Update from the repository'}]);
 if(code==='files')return make('files',`${folder?folder:'The top level'} holds files that were not saved by the manager.`,[{action:'place',label:'Choose another place'},details]);
 if(code==='settings')return make('settings','This lab’s save location has to be set up again.',[{action:'settings',label:'Save settings'},details]);
 if(code==='devices')return make('devices','No device of this lab is selected for saving.',[{action:'settings',label:'Save settings'}]);
 return make('other','The save did not work.',[again,details]);
}
// The sentence of a waiting save (HEADER.md 4.3) from the job's stored summary {devices, added, removed, topology, map, first, removed_devices}
// and the other saves the upload also sends (the review's `also_sends` rows: {job_id, lab, name, ...} for a save the manager holds,
// {commit, name, files} for one it does not). The optional `job` chooses the first sentence of a checkpoint or a folder move, which the summary does not describe.
function saveChangeSentence(summary,also,job){
 const list=(names,most)=>names.length<=most?(names.length<2?(names[0]||''):names.slice(0,-1).join(', ')+' and '+names[names.length-1]):names.slice(0,3).join(', ')+' and '+(names.length-3)+' more';
 const folderOf=p=>String(p||'').replace(/^\/+|\/+$/g,'')||'the top level';
 const parts=[];
 if(job&&job.target==='checkpoint')parts.push(job.checkpoint?`Checkpoint ${job.checkpoint} kept. It is not uploaded yet.`:'A checkpoint was kept. It is not uploaded yet.');
 else if(job&&job.target==='move')parts.push(`${job.lab_name||'The lab'}’s saved files moved to ${folderOf(job.destination?.path)}.`);
 else if(!summary||typeof summary!=='object'||Array.isArray(summary))parts.push('This save is on the lab VM and not uploaded yet.');
 else{
  const devices=(Array.isArray(summary.devices)?summary.devices:[]).map(String),gone=(Array.isArray(summary.removed_devices)?summary.removed_devices:[]).map(String);
  const what=summary.topology&&summary.map?'The topology and the map':summary.topology?'The topology':summary.map?'The map':'';
  if(summary.first){
   const kinds=[...(devices.length?[plural(devices.length,'device')]:[]),...(summary.topology?['the topology']:[]),...(summary.map?['the map']:[])];
   parts.push('This is the first save here'+(kinds.length?': '+(kinds.length<2?kinds[0]:kinds.slice(0,-1).join(', ')+' and '+kinds[kinds.length-1]):'')+'.');
  }else{
   if(devices.length){
    parts.push(`${plural(devices.length,'device')} changed since your last save: ${list(devices,4)}.`);
    if(summary.added!==undefined||summary.removed!==undefined)parts.push(`${plural(Number(summary.added)||0,'line')} added, ${Number(summary.removed)||0} removed.`);
    if(what)parts.push(what+' changed.');
   }else if(what)parts.push(what+' changed since your last save.');
   if(gone.length)parts.push(gone.length===1?`${gone[0]} is no longer saved; its file was removed.`:`${list(gone,4)} are no longer saved; their files were removed.`);
   if(!devices.length&&!what&&!gone.length)parts.push('Nothing changed since your last save, which is not uploaded yet.');
  }
 }
 const rows=Array.isArray(also)?also:[];
 if(rows.length){
  const names=rows.map(r=>{const name=String(r&&r.name||'Unnamed save');if(r&&r.job_id){const lab=r.lab&&typeof r.lab==='object'?r.lab.name:r.lab;return lab?`${name} (${lab})`:name;}return `"${name}"`;});
  parts.push(`This upload also sends ${rows.length===1?'1 other save':rows.length+' other saves'}: ${list(names,3)}.`);
 }
 return parts.join(' ');
}
