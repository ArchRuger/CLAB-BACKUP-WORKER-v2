'use strict';
// Student-facing status vocabulary. Pure functions over the /api/state document: they translate the
// backend's state machines (deployment status, NOS readiness, Git job status, operations) into the
// small set of words the UI uses everywhere. Lab: Stopped / Starting / Running / Needs attention.
// Device: Starting / Ready / Unavailable / Needs attention / Needs credentials.
// Progress: Not saved yet / Saving progress… / Saved to Git / Saved on this VM / Needs attention.
// Pills are ok | warn | danger | neutral | busy (busy = something is in progress right now).
// "Devices", never "routers"; "Not connected" is reserved for the VM. Nothing here touches the DOM,
// so the harness tests call these functions directly. operations.js keeps its own imperative table.
const STATUS_OPERATION_LABELS={deploy:'Starting lab',redeploy:'Redeploying lab',destroy:'Destroying lab',start:'Starting devices',stop:'Stopping devices',restart:'Restarting devices',apply:'Updating the lab from its topology file',save:'Saving device configurations',inspect:'Checking lab status','inspect-all':'Checking running labs',create:'Creating topology file',delete:'Deleting topology file',clone:'Downloading lab files'};
const STATUS_OPERATION_BUSY=['queued','running'];
const STATUS_OPERATION_FAILED=['failed','interrupted'];
const STATUS_GIT_BUSY=['queued','capturing','exporting','pushing'];
const STATUS_RESTORE_BUSY=['queued','preflight','backing_up','applying','confirming','verifying'];
const STATUS_RESTORE_FAILED=['failed','preflight_failed','interrupted'];
const STATUS_BADGE_LABELS={reachable:'Login OK',unreachable:'Login failed',succeeded:'Succeeded',failed:'Failed',interrupted:'Interrupted',partial:'Partly succeeded',queued:'Queued',running:'Running',Ready:'Ready'};
const STATUS_TELEMETRY_LINES={partial:'Some devices are not reporting — open Telemetry settings.',waiting:'Waiting for devices to finish starting.',unsupported:'None of this lab’s devices support telemetry.',disabled:'Telemetry is off for this lab.',unmonitored:'Available once the lab is running on the VM.'};
function plural(count,word,pluralWord){const n=Number(count)||0;return n+' '+(n===1?word:(pluralWord||word+'s'));}
function operationLabel(action){return STATUS_OPERATION_LABELS[action]||'Lab operation';}
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
 const restore=(ctx.restore_jobs||[]).find(j=>STATUS_RESTORE_BUSY.includes(j.status)&&mine(j));
 const save=(ctx.git_jobs||[]).find(j=>STATUS_GIT_BUSY.includes(j.status)&&mine(j));
 const backup=(ctx.jobs||[]).find(j=>STATUS_OPERATION_BUSY.includes(j.status)&&mine(j));
 return {operation,restore,save,backup};
}
// The newest finished operation or restore job of the lab, when it ended badly and the student has
// not dismissed it (ctx.dismissed is a Set of job ids). A later job that finished cleanly clears it,
// so "Try again" succeeding never leaves a stale warning behind.
function labFailure(lab,ctx={}){
 const dismissed=ctx.dismissed,isDismissed=id=>!!dismissed&&(typeof dismissed.has==='function'?dismissed.has(id):Array.isArray(dismissed)&&dismissed.includes(id));
 const done=[];
 for(const j of ctx.operations||[])if(j.lab_id===lab?.id&&!STATUS_OPERATION_BUSY.includes(j.status))done.push({job:j,failed:STATUS_OPERATION_FAILED.includes(j.status),label:operationLabel(j.action)});
 for(const j of ctx.restore_jobs||[])if(j.lab_id===lab?.id&&!STATUS_RESTORE_BUSY.includes(j.status))done.push({job:j,failed:STATUS_RESTORE_FAILED.includes(j.status),label:'Replacing configuration'});
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
 if(activity.operation)return {key:'working',label:operationLabel(activity.operation.action),detail:activity.operation.message||'Running on the lab VM.',ready,total,pill:'busy',job:activity.operation};
 if(activity.restore)return {key:'working',label:'Replacing configuration',detail:activity.restore.message||'Applying a saved configuration.',ready,total,pill:'busy',job:activity.restore};
 const failure=labFailure(lab,ctx);
 if(failure)return {key:'attention',label:'Needs attention',detail:`${failure.label} did not finish.`,ready,total,pill:'danger',job:failure.job};
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
 if(node.ssh_ready)return {key:'ready',label:'Ready',detail:login==='unmonitored'?'Connected with the saved address.':`${name} is accepting SSH logins.`,next:'',cli:true,pill:'ok'};
 if(statusNotRunning(node))return {key:'unavailable',label:'Unavailable',detail:`${name} is not running, or the lab status is out of date.`,next:'Start lab',cli:false,pill:'neutral'};
 if(login==='booting')return {key:'starting',label:'Starting',detail:`${name} is still starting. SSH opens automatically when it answers.`,next:'',cli:false,pill:'warn'};
 if(login==='failed')return {key:'attention',label:'Needs attention',detail:`${name} is running, but SSH login failed with the saved credentials.`,next:'Check credentials',cli:false,pill:'danger'};
 if(statusNeedsCredentials(node))return {key:'credentials',label:'Needs credentials',detail:`Add login credentials to open the CLI of ${name}.`,next:'Add credentials',cli:false,pill:'warn'};
 if(!node.platform||node.readiness==='Choose NOS')return {key:'credentials',label:'Choose network OS',detail:`Tell the manager which network OS ${name} runs.`,next:'Edit connection',cli:false,pill:'warn'};
 return {key:'unknown',label:'Unknown',detail:'',next:'',cli:false,pill:'neutral'};
}
// How many devices of the lab cannot open a CLI until login credentials are added.
function credentialsNeeded(lab){return (lab?.nodes||[]).filter(statusNeedsCredentials).length;}
// The Git job that describes where the lab's progress stands: newest first, ignoring dismissed
// jobs and repository update markers.
function statusLabGitJobs(lab,gitJobs){return (gitJobs||[]).filter(j=>j.lab_id===lab?.id&&j.target!=='update').sort((a,b)=>String(b.created||'').localeCompare(String(a.created||'')));}
function latestProgressJob(lab,gitJobs){return statusLabGitJobs(lab,gitJobs).find(j=>j.status!=='dismissed');}
// Progress state → {key,label,detail,at,pill,job}. `at` is the timestamp the label refers to.
// `problem` is repository_status.problem: when the save location itself is broken the answer is
// "Needs attention" whatever the last job says. The upload target is named by its host
// ("github.com") or, when the push URL is unknown, "the online repository".
function progressState(lab,gitJobs,now,problem){
 if(!lab?.git_binding)return {key:'unconnected',label:'No save location yet',detail:'Choose where this lab’s progress is saved.',at:'',pill:'neutral',job:null};
 const host=statusHost(lab.git_binding.repository?.push_url)||'the online repository';
 const job=latestProgressJob(lab,gitJobs),at=job?(job.finished||job.created||''):'',when=relativeTime(at,now);
 const phase=job&&{queued:'Waiting to start…',capturing:'Reading device configurations…',exporting:job.target==='move'?'Moving saved files…':'Saving to the repository…',pushing:`Uploading to ${host}…`}[job.status];
 if(phase)return {key:'saving',label:'Saving progress…',detail:phase,at,pill:'busy',job};
 if(problem)return {key:'attention',label:'Needs attention',detail:'Saving to Git is not possible right now.',at,pill:'warn',job:job||null,problem:String(problem)};
 if(!job){
  const kept=statusLabGitJobs(lab,gitJobs)[0];
  if(kept)return {key:'kept',label:'Kept on this VM',detail:'Your last save was kept on the VM without uploading.',at:kept.finished||kept.created||'',pill:'neutral',job:kept};
  return {key:'none',label:'Not saved yet',detail:'Save progress creates a snapshot you can return to later.',at:'',pill:'neutral',job:null};
 }
 const table={
  synced:{key:'git',label:'Saved to Git',detail:when?`Saved ${when}.`:'',pill:'ok'},
  unchanged:{key:'git',label:'Saved to Git',detail:'Nothing changed since your last save.',pill:'ok'},
  committed:{key:'local',label:'Saved on this VM',detail:'Not uploaded yet. Upload it when you are ready.',pill:'warn'},
  review_pending:{key:'review',label:'Saved on this VM',detail:'Review the changes before uploading.',pill:'warn'},
  push_pending:{key:'attention',label:'Needs attention',detail:`Saved on this VM, but it could not be uploaded to ${host}.`,pill:'warn'},
  export_pending:{key:'attention',label:'Needs attention',detail:'Device configurations were read, but they could not be saved to the repository.',pill:'warn'},
  capture_incomplete:{key:'failed',label:'Save failed',detail:'A device could not be read, so nothing was saved. Check that every included device is Ready, then try again.',pill:'danger'},
  failed:{key:'failed',label:'Save failed',detail:'The last save did not complete.',pill:'danger'},
  interrupted:{key:'interrupted',label:'Save interrupted',detail:'The manager restarted during the last save. Retry it.',pill:'warn'},
 }[job.status]||{key:'unknown',label:String(job.status||'Unknown'),detail:job.message||'',pill:'neutral'};
 return {...table,at,job};
}
// One line for the lab header: "Saved to Git 12 minutes ago" or "Saving progress…".
function progressSummary(lab,gitJobs,now,problem){const p=progressState(lab,gitJobs,now,problem);if(['git','local','review','kept'].includes(p.key))return p.label+(p.at?' '+relativeTime(p.at,now):'');return p.label;}
// Backup / login-check badges in the technical table and job list; unknown values pass through and
// the caller keeps the raw value in `title`.
function badgeLabel(status){return STATUS_BADGE_LABELS[status]||String(status??'');}
// One sentence for the Tools › Telemetry card from lab.telemetry ({status, total, streaming, failed, …}).
function telemetryLine(status,summary){
 if(status&&typeof status==='object'){summary=status;status=summary.status;}const s=summary||{};
 if(status==='streaming')return `Collecting live data from ${plural(s.streaming??s.total??0,'device')}.`;
 if(status==='failed')return `${plural(s.failed??0,'device')} could not be set up for telemetry.`;
 return STATUS_TELEMETRY_LINES[status]||'';
}
// A student-facing name for a saved-version folder the instructor put in the repository: the last
// path segment through a small map, otherwise the segment itself (callers show the full path as a caption).
function savedVersionName(folder){
 const name=String(folder||'').replace(/\/+$/,'').split('/').pop()||'';
 if(/^(solution|final)$/i.test(name))return 'Final state (instructor)';
 if(/^(start|base|initial)$/i.test(name))return 'Starting state';
 const broken=name.match(/^broken[-_]?(\d+)$/i);if(broken)return `Troubleshooting scenario ${broken[1]}`;
 return name;
}
