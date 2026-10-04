// Student-facing status vocabulary: the words the UI uses for a lab, a device and saved progress.
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
function makeContext(){const context=vm.createContext({console});vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/status.js'),'utf8'),context);return context;}
const NOW=Date.parse('2026-09-16T12:00:00Z');
const running={id:'lab',name:'BGP',nodes:[{name:'r1',runtime_state:'running',ssh_ready:true,login_configured:true,nos_login:{status:'ready'}},{name:'r2',runtime_state:'running',ssh_ready:true,login_configured:true,nos_login:{status:'ready'}}],deployment:{status:'Running'},nos_readiness:{status:'ready',total:2,ready:2,booting:0,failed:0}};
const PILLS=['ok','warn','danger','neutral','busy'];

test('a lab reads Stopped, Starting, Running or Needs attention — never container words',()=>{
 const c=makeContext();
 assert.deepEqual(pick(c.labState(running)),{key:'running',label:'Running',detail:'2 of 2 devices ready',pill:'ok'});
 const booting=c.labState({...running,nodes:[running.nodes[0],{name:'r2',ssh_ready:false,login_configured:true,nos_login:{status:'booting'}}],nos_readiness:{status:'booting',total:2,ready:1,booting:1,failed:0}});
 assert.equal(booting.label,'Starting');assert.match(booting.detail,/1 of 2 devices ready\. SSH becomes available automatically/);assert.equal(booting.pill,'warn');
 const failed=c.labState({...running,nodes:[running.nodes[0],{name:'r2',ssh_ready:false,login_configured:true,nos_login:{status:'failed'}}],nos_readiness:{status:'failed',total:2,ready:1,booting:0,failed:1}});
 assert.equal(failed.label,'Needs attention');assert.match(failed.detail,/SSH login failed on 1 device\. 1 of 2 devices ready\./);assert.equal(failed.pill,'danger');
 assert.equal(c.labState({...running,deployment:{status:'Not deployed'}}).label,'Stopped');
 assert.equal(c.labState({...running,deployment:{status:'Stopped'}}).key,'stopped');
 const partial=c.labState({...running,nodes:[{runtime_state:'running'},{runtime_state:'exited'}],deployment:{status:'Partially running'}});
 assert.equal(partial.label,'Some devices stopped');assert.equal(partial.detail,'1 of 2 devices are running.');
 const unlinked=c.labState({...running,deployment:{status:'Unlinked'}});
 assert.equal(unlinked.label,'Not matched to a running lab');assert.equal(unlinked.detail,'The manager cannot tell which lab on the VM this is.');assert.equal(unlinked.key,'unlinked');
 const unknown=c.labState({...running,deployment:{status:'Unknown'}},{discovery:{configured:true}});
 assert.equal(unknown.label,'Status unknown');assert.equal(unknown.detail,'The lab VM cannot be reached right now, so this status may be out of date.');
 assert.match(c.labState({...running,deployment:{status:'Unknown'}},{discovery:{configured:false}}).detail,/Connect the lab VM/);
 const idle=c.labState({...running,nodes:[{name:'r1'},{name:'r2'}],nos_readiness:{status:'idle',total:0,ready:0}});
 assert.equal(idle.label,'Running');assert.equal(idle.detail,'0 of 2 devices ready','idle readiness still counts every device — never "Devices are running."');
 for(const lab of [running,{...running,deployment:{status:'Unlinked'}},{...running,deployment:{status:'Unknown'}}])assert.ok(PILLS.includes(c.labState(lab).pill));
 assert.doesNotMatch(JSON.stringify(c.labState(running)),/container|discover|NOS|worker|router/i);
});

test('every device counts: ready, needing credentials and not running are all in the header line',()=>{
 const c=makeContext();
 const lab={...running,nodes:[...running.nodes,{name:'r3',ssh_ready:false,login_configured:false,nos_login:{status:'needs_credentials'}},{name:'r4',ssh_ready:false,available:false,nos_login:{status:'unavailable'}}],nos_readiness:{status:'ready',total:2,ready:2,booting:0,failed:0}};
 const s=c.labState(lab);
 assert.equal(s.total,4);assert.equal(s.ready,2);assert.equal(s.label,'Running');
 assert.equal(s.detail,'2 of 4 devices ready · 1 needs login credentials · 1 not running');
 assert.equal(c.credentialsNeeded(lab),1);
 const two={...lab,nodes:[...lab.nodes,{name:'r5',ssh_ready:false,login_configured:false,nos_login:{status:'needs_credentials'}}]};
 assert.match(c.labState(two).detail,/2 of 5 devices ready · 2 need login credentials · 1 not running/);assert.equal(c.credentialsNeeded(two),2);
 assert.equal(c.credentialsNeeded(running),0);assert.equal(c.credentialsNeeded({nodes:[{name:'x',ssh_ready:false,available:false,login_configured:false}]}),0,'a stopped device is "not running", not "needs credentials"');
 assert.equal(c.credentialsNeeded({nodes:[{name:'u',ssh_ready:false,login_configured:false,nos_login:{status:'unmonitored'}}]}),1,'an unmatched lab still reports missing logins');
 assert.equal(c.credentialsNeeded(null),0);
 const starting={...lab,nos_readiness:{status:'booting',total:3,ready:2,booting:1,failed:0}};
 assert.equal(c.labState(starting).detail,'2 of 4 devices ready · 1 needs login credentials · 1 not running. SSH becomes available automatically.');
});

test('an operation or restore in progress takes priority and is named as a task',()=>{
 const c=makeContext();
 const op=c.labState(running,{operations:[{id:'o1',lab_id:'lab',action:'deploy',status:'running',message:'Executing on the VM'}]});
 assert.equal(op.key,'working');assert.equal(op.label,'Starting lab');assert.equal(op.pill,'busy');assert.equal(op.job.id,'o1');
 assert.equal(c.labState(running,{operations:[{lab_id:'other',action:'destroy',status:'running'}]}).label,'Running','another lab\'s operation does not change this lab');
 assert.equal(c.labState(running,{operations:[{lab_id:'lab',action:'destroy',status:'succeeded'}]}).label,'Running');
 const restore=c.labState(running,{restore_jobs:[{id:'r1',lab_id:'lab',status:'applying',message:'Applying the saved configuration.'}]});
 assert.equal(restore.label,'Loading a saved state');assert.equal(restore.pill,'busy');assert.equal(restore.job.id,'r1');
 assert.equal(c.labState(running,{operations:[{lab_id:'lab',action:'apply',status:'queued'}]}).label,'Updating the lab from its topology file');
 assert.equal(c.operationLabel('redeploy'),'Redeploying lab');assert.equal(c.operationLabel('apply'),'Updating the lab from its topology file');assert.equal(c.operationLabel('made-up'),'Lab operation');
 assert.doesNotMatch(c.operationLabel('apply')+c.operationLabel('deploy'),/Applying topology/);
});

test('an operation or restore that did not finish needs attention until it is dismissed or redone',()=>{
 const c=makeContext(),stopped={...running,deployment:{status:'Not deployed'}};
 const failed={id:'op-1',lab_id:'lab',action:'deploy',status:'failed',created:'2026-09-16T11:00:00Z',finished:'2026-09-16T11:01:00Z',message:'Host command returned an error'};
 const s=c.labState(stopped,{operations:[failed]});
 assert.equal(s.key,'attention');assert.equal(s.label,'Needs attention');assert.equal(s.detail,'Starting lab did not finish.');assert.equal(s.pill,'danger');assert.equal(s.job.id,'op-1');
 assert.equal(c.labState(stopped,{operations:[{...failed,status:'interrupted'}]}).detail,'Starting lab did not finish.');
 assert.equal(c.labState(stopped,{operations:[failed],dismissed:new Set(['op-1'])}).label,'Stopped','dismissing the failure shows the plain lab state again');
 assert.equal(c.labState(stopped,{operations:[failed],dismissed:['op-1']}).label,'Stopped','an array of ids is accepted too');
 assert.equal(c.labState(stopped,{operations:[{...failed,lab_id:'other'}]}).label,'Stopped','another lab\'s failure is not ours');
 const redone={id:'op-2',lab_id:'lab',action:'deploy',status:'succeeded',created:'2026-09-16T11:05:00Z',finished:'2026-09-16T11:06:00Z'};
 assert.equal(c.labState(running,{operations:[failed,redone]}).label,'Running','a later successful operation clears the old failure');
 assert.equal(c.labState(stopped,{operations:[redone,{...failed,id:'op-3',created:'2026-09-16T11:10:00Z',finished:'2026-09-16T11:11:00Z'}]}).label,'Needs attention','the newest outcome wins whatever the array order');
 assert.equal(c.labState(running,{operations:[failed,{id:'op-4',lab_id:'lab',action:'deploy',status:'running',created:'2026-09-16T11:20:00Z'}]}).label,'Starting lab','a running retry outranks the old failure');
 const restore=c.labState(running,{restore_jobs:[{id:'rs-1',lab_id:'lab',status:'preflight_failed',created:'2026-09-16T11:30:00Z'}]});
 assert.equal(restore.label,'Needs attention');assert.equal(restore.detail,'Loading a saved state did not finish.');assert.equal(restore.job.id,'rs-1');
 assert.equal(c.labState(running,{restore_jobs:[{id:'rs-2',lab_id:'lab',status:'failed',created:'2026-09-16T11:30:00Z'}]}).key,'attention');
 assert.equal(c.labState(running,{restore_jobs:[{id:'rs-3',lab_id:'lab',status:'succeeded',created:'2026-09-16T11:30:00Z'}]}).label,'Running');
 assert.equal(c.labState(running,{restore_jobs:[{id:'rs-2',lab_id:'lab',status:'failed',created:'2026-09-16T11:30:00Z'}],operations:[redone]}).label,'Needs attention','the restore failure is newer than the deploy');
});

test('a device explains itself in one sentence and says whether the CLI can open',()=>{
 const c=makeContext();
 const ready=c.deviceState({name:'clab-bgp-r1',short_name:'R1',ssh_ready:true,nos_login:{status:'ready'}});
 assert.equal(ready.label,'Ready');assert.equal(ready.cli,true);assert.match(ready.detail,/R1 is accepting SSH logins/);
 const booting=c.deviceState({name:'R2',ssh_ready:false,login_configured:true,nos_login:{status:'booting'}});
 assert.equal(booting.label,'Starting');assert.equal(booting.cli,false);assert.match(booting.detail,/R2 is still starting\. SSH opens automatically/);
 // The disabled Open CLI reason points at the refresh control, both the rail-wide one and this device's own.
 assert.match(booting.detail,/Use Test logins \(above\) or this device's Test login \(in its panel, under Advanced\) to check again now\./);
 const failed=c.deviceState({name:'R3',ssh_ready:false,login_configured:true,nos_login:{status:'failed'}});
 assert.equal(failed.label,'Needs attention');assert.match(failed.detail,/R3 is running, but SSH login failed/);assert.equal(failed.next,'Check credentials');assert.equal(failed.pill,'danger');
 const down=c.deviceState({name:'R4',ssh_ready:false,available:false,nos_login:{status:'unavailable'}});
 assert.equal(down.label,'Unavailable');assert.equal(down.next,'Start lab');assert.equal(down.detail,'R4 is not running, or the lab status is out of date.');
 const creds=c.deviceState({name:'R5',ssh_ready:false,login_configured:false,nos_login:{status:'needs_credentials'}});
 assert.equal(creds.label,'Needs credentials');assert.equal(creds.next,'Add credentials');
 assert.match(creds.detail,/Add login credentials to open the CLI of R5\./);assert.match(creds.detail,/Add them under Devices, then use Test logins to check again\./);
 assert.equal(c.deviceState({name:'R6',ssh_ready:false,platform:'',readiness:'Choose NOS'}).label,'Choose network OS');
 const manual=c.deviceState({name:'R7',ssh_ready:true,nos_login:{status:'unmonitored'}});
 assert.equal(manual.label,'Ready');assert.equal(manual.detail,'Connected with the saved address.');assert.equal(manual.cli,true);
 // A refresh in flight is never optimistic: no CLI, a distinct label and pill, until a real answer lands.
 const checking=c.deviceState({name:'R8',ssh_ready:false,login_configured:true,nos_login:{status:'checking'}});
 assert.equal(checking.label,'Testing login…');assert.equal(checking.cli,false);assert.equal(checking.pill,'busy');assert.match(checking.detail,/Testing the SSH login of R8/);
 assert.equal(c.deviceState(null).cli,false);
 for(const n of [ready,booting,failed,down,creds,manual,checking])assert.ok(PILLS.includes(n.pill),n.label);
 assert.doesNotMatch(JSON.stringify([ready,booting,failed,down,creds,manual,checking]),/router|stale|Not connected/i);
});

// progressState and progressSummary went with the Progress tab (D1; PROMPT 5.2: one status function). Their claims are the chip's.
test('the chip reads Not saved yet, Saving…, Saved, 1 save to upload, Upload failed or Can’t save (the one status function, saveChipState)',()=>{
 const c=makeContext(),lab={id:'lab',git_binding:{binding_id:'b'}},state=(l,jobs)=>plain(c.saveChipState(l,{git_jobs:jobs},Date.parse('2026-09-16T12:00:30Z')));
 const none=state({id:'lab'},[]);
 assert.equal(none.text,'Not saved yet');assert.equal(none.key,'none');assert.equal(none.panel,'first','a lab without a save location opens the first-save view');
 assert.equal(state(lab,[]).text,'Not saved yet');
 const job=(status,extra={})=>({id:status,lab_id:'lab',status,target:'latest',commit:['committed','review_pending','push_pending','synced'].includes(status)?'c-'+status:'',pushed:status==='synced',created:'2026-09-16T11:48:00Z',finished:'2026-09-16T11:48:30Z',...extra});
 const synced=state(lab,[job('synced')]);
 assert.equal(synced.text,'Saved 12 min ago');assert.equal(synced.dot,'ok');assert.equal(synced.key,'saved');
 const pushing=state(lab,[job('pushing')]);
 assert.equal(pushing.text,'Uploading…');assert.equal(pushing.dot,'busy');assert.equal(pushing.saveDisabled,true);
 assert.equal(state(lab,[job('capturing')]).text,'Saving…');assert.equal(state(lab,[job('exporting',{target:'move'})]).text,'Saving…');
 const pending=state(lab,[job('push_pending')]);assert.equal(pending.text,'Upload failed');assert.equal(pending.dot,'bad');
 const local=state(lab,[job('committed')]);assert.equal(local.text,'1 save to upload');assert.equal(local.dot,'warn');assert.equal(local.key,'waiting');
 assert.equal(state(lab,[job('review_pending')]).panel,'upload','the review is the upload panel: the sentence, Upload, Not now, See changes');
 assert.equal(state(lab,[job('failed')]).text,'Can’t save');assert.equal(state(lab,[job('capture_incomplete')]).dot,'bad');
 assert.equal(state(lab,[job('interrupted')]).text,'Can’t save');
 // newest first, ignoring dismissed jobs and repository update markers, and other labs
 const newest=state(lab,[job('failed',{created:'2026-09-16T10:00:00Z',finished:'2026-09-16T10:00:30Z'}),job('synced',{created:'2026-09-16T11:00:00Z',finished:'2026-09-16T11:00:30Z'}),job('dismissed',{created:'2026-09-16T11:30:00Z'}),job('push_pending',{created:'2026-09-16T11:40:00Z',target:'update'}),job('failed',{created:'2026-09-16T11:50:00Z',lab_id:'other'})]);
 assert.equal(newest.key,'saved');
});
test('the chip and its problem name the upload host, know unchanged and kept-only saves, and flag a broken save location',()=>{
 const c=makeContext(),job=(status,extra={})=>({id:status,lab_id:'lab',status,target:'latest',commit:['committed','review_pending','push_pending','synced','unchanged'].includes(status)?'c-'+status:'',pushed:['synced','unchanged'].includes(status),created:'2026-09-16T11:48:00Z',finished:'2026-09-16T11:48:30Z',...extra});
 const at=Date.parse('2026-09-16T12:00:30Z'),state=(l,jobs)=>plain(c.saveChipState(l,{git_jobs:jobs},at));
 const withUrl=push_url=>({id:'lab',git_binding:{binding_id:'b',repository:{push_url}},git_status:{checked:true,ready:false,problem:'x',code:'account',waiting:0}});
 const sentence=push_url=>c.saveProblem(withUrl(push_url),{}).sentence;
 assert.equal(sentence('https://github.com/course/labs.git'),'The VM account cannot upload to github.com.');
 assert.equal(sentence('git@gitlab.example.edu:course/labs.git'),'The VM account cannot upload to gitlab.example.edu.');
 assert.equal(sentence('ssh://git@git.school.local:2222/labs.git'),'The VM account cannot upload to git.school.local.');
 assert.equal(sentence('nonsense'),'The VM account cannot upload to the online repository.');
 const github={id:'lab',git_binding:{binding_id:'b',repository:{push_url:'https://github.com/course/labs.git'}},git_status:{checked:true,ready:true,problem:'',code:'',waiting:0}};
 const unchanged=state(github,[job('unchanged')]);
 assert.equal(unchanged.key,'saved');assert.equal(unchanged.text,'Saved 12 min ago');assert.equal(unchanged.dot,'ok');
 const incomplete=c.saveProblem(github,{git_jobs:[job('capture_incomplete')]});
 assert.equal(state(github,[job('capture_incomplete')]).text,'Can’t save');assert.equal(incomplete.sentence,'A device could not be read, so nothing was saved.');
 const kept=state(github,[job('dismissed')]);
 assert.equal(kept.text,'Kept on this VM');assert.equal(kept.key,'kept');assert.equal(kept.job.id,'dismissed');
 assert.equal(state(github,[job('dismissed',{target:'update'})]).text,'Not saved yet','a repository update marker is not a save');
 assert.equal(state(github,[job('dismissed',{created:'2026-09-16T11:50:00Z'}),job('synced',{created:'2026-09-16T11:00:00Z'})]).key,'saved','an earlier real save still counts');
 const broken={...github,git_status:{checked:true,ready:false,problem:'The push URL rejected the VM account.',code:'account',waiting:0}};
 const problem=state(broken,[job('synced')]);
 assert.equal(problem.key,'cant');assert.equal(problem.text,'Can’t save');assert.equal(problem.dot,'bad');assert.equal(problem.detail,'The push URL rejected the VM account.');assert.equal(problem.code,'account');
 assert.equal(state(broken,[]).text,'Can’t save','a broken location matters before the first save too');
 assert.equal(state(broken,[job('pushing')]).text,'Uploading…','a save already running still reports its phase');
 assert.equal(state({id:'lab',git_status:{checked:true,ready:false,problem:'broken',code:'other',waiting:0}},[]).text,'Not saved yet');
 const all=['synced','unchanged','committed','review_pending','push_pending','export_pending','capture_incomplete','failed','interrupted','dismissed','pushing'].map(s=>state(github,[job(s)]));
 for(const p of all)assert.ok(['ok','warn','bad','none','busy','info'].includes(p.dot),p.text);
 assert.doesNotMatch(JSON.stringify(all.map(p=>[p.text,p.detail])),/GitHub|router|Not connected/);
 assert.equal(typeof c.progressState,'undefined');assert.equal(typeof c.progressSummary,'undefined');
});
test('relative times stay human and never print NaN',()=>{
 const c=makeContext();
 assert.equal(c.relativeTime('2026-09-16T11:59:40Z',NOW),'just now');
 assert.equal(c.relativeTime('2026-09-16T11:48:00Z',NOW),'12 minutes ago');
 assert.equal(c.relativeTime('2026-09-16T11:59:00Z',NOW),'1 minute ago');
 assert.equal(c.relativeTime('2026-09-16T09:00:00Z',NOW),'3 hours ago');
 assert.equal(c.relativeTime('2026-09-15T09:00:00Z',NOW),'yesterday');
 assert.equal(c.relativeTime('2026-09-13T09:00:00Z',NOW),'3 days ago');
 assert.match(c.relativeTime('2026-01-01T09:00:00Z',NOW),/2026/);
 assert.equal(c.relativeTime(1789128000,NOW),'5 days ago','Git Unix seconds are accepted');
 assert.equal(c.relativeTime('not a date',NOW),'');assert.equal(c.relativeTime('',NOW),'');assert.equal(c.relativeTime(null,NOW),'');
 assert.equal(c.plural(1,'device'),'1 device');assert.equal(c.plural(2,'device'),'2 devices');
});

test('badges and saved-version names use student words',()=>{
 const c=makeContext();
 assert.equal(c.badgeLabel('reachable'),'Login OK');assert.equal(c.badgeLabel('unreachable'),'Login failed');
 assert.equal(c.badgeLabel('succeeded'),'Succeeded');assert.equal(c.badgeLabel('failed'),'Failed');assert.equal(c.badgeLabel('interrupted'),'Interrupted');
 assert.equal(c.badgeLabel('partial'),'Partly succeeded');assert.equal(c.badgeLabel('queued'),'Queued');assert.equal(c.badgeLabel('running'),'Running');assert.equal(c.badgeLabel('Ready'),'Ready');
 assert.equal(c.badgeLabel('Needs credentials'),'Needs credentials','unknown values pass through');assert.equal(c.badgeLabel(undefined),'');
 // Rewritten with DESIGN.md 3.8 N3 and LOAD.md 2.2 (owner decision D-5.4 step 1: a lab state shows its own name, never an instructor-word mapping):
 // the last folder name once a trailing `latest` is dropped, first letter upper-cased only when the name is all lower case. The special cases are gone.
 assert.equal(c.savedVersionName('labs/BGP-LAB/reference/solution'),'Solution');
 assert.equal(c.savedVersionName('bgp-core/reference/final/'),'Final');
 assert.equal(c.savedVersionName('bgp-core/reference/start'),'Start');assert.equal(c.savedVersionName('base'),'Base');assert.equal(c.savedVersionName('Initial'),'Initial');
 assert.equal(c.savedVersionName('bgp-core/reference/broken-01'),'Broken-01');assert.equal(c.savedVersionName('broken_2'),'Broken_2');
 assert.equal(c.savedVersionName('bgp-core/work'),'Work');assert.equal(c.savedVersionName('ARISTA-LAB-TEST'),'ARISTA-LAB-TEST');assert.equal(c.savedVersionName(''),'');
});

function pick(o){return {key:o.key,label:o.label,detail:o.detail,pill:o.pill};}

test('a device that Restart device is running for reads Restarting, and the lab names the device it restarts',()=>{
 const c=makeContext();
 const restarting=c.deviceState({name:'clab-bgp-r1',short_name:'R1',ssh_ready:false,available:false,login_configured:true,nos_login:{status:'restarting'}});
 assert.equal(restarting.label,'Restarting');assert.equal(restarting.key,'working');assert.equal(restarting.cli,false);assert.equal(restarting.pill,'busy');
 assert.match(restarting.detail,/R1 is restarting on the VM\. Its CLI opens again once it accepts a login\./);
 assert.equal(c.operationLabel('restart-node'),'Restarting device');
 assert.equal(c.operationLabel('restart-node',{node_label:'ceos'}),'Restarting ceos');
 assert.equal(c.operationLabel('restart',{node_label:'ceos'}),'Restarting all devices','only Restart device names a device; the lab-wide word says all (U-17)');
 const job={id:'j',lab_id:'lab',action:'restart-node',status:'running',node:'clab-bgp-r1',node_label:'R1',message:'Executing on the VM'};
 const ls=c.labState(running,{operations:[job]});
 assert.equal(ls.key,'working');assert.equal(ls.label,'Restarting R1');assert.equal(ls.job,job);assert.equal(ls.pill,'busy');assert.equal(ls.detail,'Executing on the VM');
 assert.doesNotMatch(JSON.stringify([restarting,ls]),/container|docker/i);
});

test('M-15: a restore that ends needs_attention or partial reaches the lab level with its own headline, and can be dismissed',()=>{
 const c=makeContext();
 const job=(id,status,at)=>({id,lab_id:'lab',status,created:at,finished:at});
 const attention=c.labState(running,{restore_jobs:[job('rs-1','needs_attention','2026-09-16T11:30:00Z')]});
 assert.equal(attention.key,'attention');assert.equal(attention.label,'Needs attention');assert.equal(attention.job.id,'rs-1');
 assert.match(attention.detail,/needs a check on some devices/);assert.doesNotMatch(attention.detail,/did not finish/);
 const partial=c.labState(running,{restore_jobs:[job('rs-2','partial','2026-09-16T11:30:00Z')]});
 assert.equal(partial.key,'attention');assert.match(partial.detail,/some devices only/);assert.notEqual(partial.detail,attention.detail);
 for(const state of [attention,partial])assert.ok(PILLS.includes(state.pill));
 assert.equal(c.labState(running,{restore_jobs:[job('rs-1','needs_attention','2026-09-16T11:30:00Z')],dismissed:new Set(['rs-1'])}).label,'Running','dismissing it shows the plain lab state again');
 const oldFailure={id:'op-1',lab_id:'lab',action:'deploy',status:'failed',created:'2026-09-16T11:00:00Z',finished:'2026-09-16T11:01:00Z'};
 const both=c.labState(running,{operations:[oldFailure],restore_jobs:[job('rs-3','needs_attention','2026-09-16T11:30:00Z')]});
 assert.equal(both.job.id,'rs-3','the newest outcome is shown');
 const afterDismiss=c.labState(running,{operations:[oldFailure],restore_jobs:[job('rs-3','needs_attention','2026-09-16T11:30:00Z')],dismissed:new Set(['rs-3'])});
 assert.equal(afterDismiss.label,'Running','a dismissed newest job stays dismissed (the older failure is not resurrected)');
 assert.equal(c.labState(running,{restore_jobs:[job('rs-4','dismissed','2026-09-16T11:30:00Z')]}).label,'Running');
});

test('L-10 follow-up: a restore still reading devices back after a manager restart is work in progress, not a finished job',()=>{
 const c=makeContext();
 const job=extra=>({id:'rs-r',lab_id:'lab',status:'interrupted',created:'2026-09-16T11:30:00Z',finished:'2026-09-16T11:31:00Z',message:'Manager restarted during a restore.',...extra});
 const checking=c.labState(running,{restore_jobs:[job({rechecking:true})]});
 assert.equal(checking.key,'working');assert.equal(checking.label,'Checking devices');assert.equal(checking.pill,'busy');assert.equal(checking.job.id,'rs-r');
 assert.match(checking.detail,/manager restarted/i);assert.match(checking.detail,/reading back the devices/);
 assert.match(checking.detail,/Backups and configuration changes on this lab, and Git saves and lab operations on every lab, cannot be started until it has finished/,'the hold is named: every refused action is on this list, and refused, not queued');
 assert.doesNotMatch(checking.detail,/\bwait\b/,'review I5: the manager refuses these actions; nothing waits for the read-back');
 assert.doesNotMatch(checking.detail,/did not finish/);
 assert.ok(c.statusRestoreActive(job({rechecking:true})));assert.ok(!c.statusRestoreActive(job({rechecking:false})));
 // Read back (false) or stored by an older manager (no field): the finished "did not finish" job it always was.
 for(const done of [job({rechecking:false}),job({})]){const ls=c.labState(running,{restore_jobs:[done]});assert.equal(ls.key,'attention');assert.equal(ls.detail,'Loading a saved state did not finish.');}
 assert.equal(c.labState(running,{restore_jobs:[job({rechecking:'yes'})]}).key,'attention','only a real boolean true holds');
 assert.equal(c.labState(running,{restore_jobs:[job({rechecking:true,lab_id:'other'})]}).label,'Running','another lab\'s read-back does not change this lab');
 assert.equal(c.labState(running,{restore_jobs:[job({rechecking:true})],dismissed:new Set(['rs-r'])}).key,'working','work in progress cannot be dismissed away');
 assert.equal(c.labFailure(running,{restore_jobs:[job({rechecking:true})]}),null,'it is not a finished job, so it is not a failure either');
 const older={id:'op-1',lab_id:'lab',action:'deploy',status:'failed',created:'2026-09-16T11:00:00Z',finished:'2026-09-16T11:01:00Z'};
 assert.equal(c.labFailure(running,{operations:[older],restore_jobs:[job({rechecking:true})]}).job.id,'op-1','an older failure is not hidden by a job that has not finished');
 const busyRestore=c.labState(running,{restore_jobs:[{id:'r1',lab_id:'lab',status:'applying',message:'Applying.'}]});
 assert.equal(busyRestore.label,'Loading a saved state','a running restore keeps its own words (LOAD.md 10: reworded from Replacing configuration)');
});

// The public design job carries a `rechecking` list of device names while it is read back, and no such key otherwise;
// an older manager's job without it reads as not rechecking.
test('L-10 follow-up: a network-design apply still reading devices back after a restart holds the lab and says so',()=>{
 const c=makeContext();
 const design=extra=>({id:'d1',lab_id:'lab',status:'interrupted',created:'2026-09-16T11:30:00Z',...extra});
 const checking=c.labState(running,{design_jobs:[design({rechecking:['r1']})]});
 assert.equal(checking.key,'working');assert.equal(checking.label,'Checking devices');assert.equal(checking.pill,'busy');assert.equal(checking.job.id,'d1');
 assert.match(checking.detail,/network design/);assert.match(checking.detail,/Backups and configuration changes on this lab cannot be started until it has finished/);assert.doesNotMatch(checking.detail,/\bwait\b/);
 assert.doesNotMatch(checking.detail,/every lab/,'the design read-back holds its own lab only');
 for(const idle of [design({}),design({rechecking:[]}),design({rechecking:['r1'],lab_id:'other'}),design({rechecking:['r1'],status:'succeeded'})])
  assert.equal(c.labState(running,{design_jobs:[idle]}).label,'Running',JSON.stringify(idle));
 const restore=c.labState(running,{restore_jobs:[{id:'r1',lab_id:'lab',status:'applying'}],design_jobs:[design({rechecking:['r1']})]});
 assert.equal(restore.job.id,'r1','a running restore is named first');
});

test('M-11 follow-up: a login test whose CLI did not answer yet reads Starting in the table, as in the device panel',()=>{
 const c=makeContext();
 assert.equal(c.badgeLabel('booting'),'Starting');
 assert.equal(c.badgeLabel('booting'),c.deviceState({name:'R2',ssh_ready:false,login_configured:true,nos_login:{status:'booting'}}).label,'both places use one word');
 // Review I6: while a Test login runs the stored check reads `checking`: the table says what the device panel says.
 assert.equal(c.badgeLabel('checking'),'Testing login…');
 assert.equal(c.badgeLabel('checking'),c.deviceState({name:'R2',ssh_ready:false,login_configured:true,nos_login:{status:'checking'}}).label,'both places use one word');
});
// ---- The save chip, the load state and the wording helpers (docs/git-redesign/DESIGN.md 7.1, design/HEADER.md 3, design/LOAD.md 5) -------------
const plain=o=>JSON.parse(JSON.stringify(o));
const ago=min=>new Date(NOW-min*60000).toISOString();
const bound={id:'lab',name:'BGP',git_binding:{repository:{prefix:'bgp',push_url:'https://github.com/o/r.git',path:'/srv/repo'},node_names:[]},git_status:{checked:true,ready:true,problem:'',code:'',waiting:0}};
const unbound={id:'lab',name:'BGP'};
let seq=0;
// A Git job of the lab. A save that reached a commit carries one; `synced` is uploaded.
function gj(status,min,extra={}){seq+=1;const commit=['synced','committed','review_pending','push_pending'].includes(status)?'c'+seq:'';return {id:'g'+seq,lab_id:'lab',status,target:'latest',captured:true,commit,pushed:status==='synced',created:ago(min+1),finished:ago(min),note:'',message:'',...extra};}
const tg=(name,status,extra={})=>({name,short_name:name,status,stage:'settled',...extra});
// A finished restore job of the lab; `min` is how long ago it finished.
function rj(status,min,targets,extra={}){seq+=1;return {id:'r'+seq,lab_id:'lab',status,created:ago(min+2),finished:ago(min),source:{type:'folder',path:'bgp/checkpoints/ospf-up',commit:'k1',backup_job_id:'',repository:''},targets,pre_backup_job_id:'',...extra};}
const loaded4=[tg('r1','verified'),tg('r2','verified'),tg('r3','verified'),tg('r4','verified')];
const chip=(lab,ctx={})=>{const c=makeContext();return plain(c.saveChipState(lab,ctx,NOW));};
const shape=s=>[s.key,s.dot,s.text,s.panel];

test('7.1 row 1 Loading: a restore job of the lab is active; k counts devices with a final word; Save and Load are disabled',()=>{
 const job=rj('applying',1,[tg('r1','verified'),tg('r2','applied',{stage:'checking'}),tg('r3','applying',{stage:'applying'}),tg('r4','pending',{stage:'queued'})],{finished:''});
 const s=chip(bound,{restore_jobs:[job],git_jobs:[gj('committed',5)]});
 assert.deepEqual(shape(s),['loading','busy','Loading… 1 of 4','loading']);assert.equal(s.saveDisabled,true);assert.equal(s.loadDisabled,true);assert.equal(s.load.done,1);assert.equal(s.load.total,4);
 assert.equal(s.count,1,'count is the waiting saves whichever state wins');
 const back=rj('interrupted',1,[tg('r1','interrupted',{stage:'applying',timeline:{queued:1}})],{rechecking:true});
 assert.equal(chip(bound,{restore_jobs:[back]}).text,'Checking devices…');
 const dead=rj('interrupted',1,[tg('r1','interrupted',{stage:'failed',timeline:{queued:1,settled:2}})]);
 assert.notEqual(chip(bound,{restore_jobs:[dead]}).key,'loading','an interrupted job without rechecking is not Loading');
 assert.equal(chip(bound,{restore_jobs:[{...job,targets:[]}]}).text,'Loading…');
 assert.equal(chip(bound,{restore_jobs:[{...job,lab_id:'other'}]}).key,'none','another lab\'s load never counts');
});

test('7.1 row 2 Saving: a Git job of the lab is active; Save is disabled, Load is not',()=>{
 for(const status of ['queued','capturing','exporting']){const s=chip(bound,{git_jobs:[gj(status,0)]});assert.deepEqual(shape(s),['saving','busy','Saving…','saving'],status);assert.equal(s.saveDisabled,true);assert.equal(s.loadDisabled,false);}
 assert.equal(chip(bound,{git_jobs:[gj('pushing',0)]}).text,'Uploading…');
 assert.equal(chip(bound,{git_jobs:[gj('exporting',0,{target:'update'})]}).text,'Updating…');
 assert.equal(chip(bound,{git_jobs:[gj('capturing',0,{lab_id:'other'})]}).key,'none');
});

test('7.1 row 3 Can\'t save: a failed attempt newer than the load and the capture save; also names the load, a second line the waiting saves',()=>{
 const load=rj('succeeded',30,loaded4),old=gj('synced',60),fail=gj('capture_incomplete',10);
 const s=chip(bound,{restore_jobs:[load],git_jobs:[old,fail]});
 assert.deepEqual(shape(s),['cant','bad','Can’t save','cant']);assert.equal(s.also.key,'running');assert.equal(s.also.text,'Running ospf-up');assert.equal(s.also2,null);assert.equal(s.code,'');
 const waiting=chip(bound,{restore_jobs:[load],git_jobs:[old,gj('review_pending',20,{captured:false,target:'checkpoint'}),fail]});
 assert.equal(waiting.key,'cant');assert.equal(waiting.also.key,'running');assert.equal(waiting.also2.key,'waiting');assert.equal(waiting.also2.text,'1 save to upload');assert.equal(waiting.count,1);
 for(const status of ['export_pending','failed'])assert.equal(chip(bound,{restore_jobs:[load],git_jobs:[old,gj(status,10)]}).key,'cant',status);
 assert.equal(chip(bound,{restore_jobs:[load],git_jobs:[old,gj('interrupted',10)]}).key,'cant','interrupted without a commit is a failed attempt');
 assert.equal(chip(bound,{restore_jobs:[load],git_jobs:[old,gj('interrupted',10,{commit:'x'})]}).key,'running','interrupted with a commit is waiting, not failed');
});

test('7.1 row 4 Partial: the newest load is newer than the newest capture save and did not succeed; n counts verified devices only',()=>{
 const job=rj('partial',5,[tg('r1','verified'),tg('r2','verified'),tg('r3','verified'),tg('r4','applied_unverified')]);
 const s=chip(bound,{restore_jobs:[job]});
 assert.deepEqual(shape(s),['partial','warn','Loaded 3 of 4','partial']);assert.equal(s.load.loaded,3);assert.equal(s.saveDisabled,false);
 const attention=rj('needs_attention',5,[tg('r1','verified'),tg('r2','verify_mismatch'),tg('r3','uncertain',{stage:'uncertain'})]);
 assert.equal(chip(bound,{restore_jobs:[attention]}).text,'Loaded 1 of 3');
 const none=rj('partial',5,[tg('r1','uncertain',{stage:'uncertain'}),tg('r2','failed')]);
 assert.equal(chip(bound,{restore_jobs:[none]}).text,'Loaded 0 of 2');
 for(const status of ['rolled_back','failed','uncertain'])assert.equal(chip(bound,{restore_jobs:[rj('partial',5,[tg('r1','verified'),tg('r2',status,status==='uncertain'?{stage:'uncertain'}:{})])]}).load.loaded,1,status+' is never counted as loaded');
 const withUpload=chip(bound,{restore_jobs:[job],git_jobs:[gj('push_pending',20)]});assert.equal(withUpload.also.key,'failed');assert.equal(withUpload.also.text,'Upload failed');
});

test('7.1 row 5 Running: the newest load succeeded and is newer than the newest capture save; also is the highest of rows 6 to 8',()=>{
 const job=rj('succeeded',5,loaded4);
 const s=chip(bound,{restore_jobs:[job]});
 assert.deepEqual(shape(s),['running','info','Running ospf-up','running']);assert.equal(s.also,null);
 const named=chip(bound,{restore_jobs:[job],git_jobs:[gj('review_pending',90,{captured:false,target:'checkpoint'})]});assert.equal(named.also.key,'waiting');assert.equal(named.also.text,'1 save to upload');assert.equal(named.count,1);
 const unready=chip({...bound,git_status:{checked:true,ready:false,problem:'x',code:'vm',waiting:0}},{restore_jobs:[job]});assert.equal(unready.key,'running');assert.equal(unready.also.key,'cant');
 const both=chip({...bound,git_status:{checked:true,ready:false,code:'vm'}},{restore_jobs:[job],git_jobs:[gj('push_pending',20)]});assert.equal(both.also.key,'cant','Can\'t save is higher than Upload failed');
});

test('7.1 row 6 Can\'t save: a failed attempt newer than the capture save, or git_status not ready; also is Upload failed or waiting saves',()=>{
 const save=gj('synced',30);
 const stopped=chip(bound,{git_jobs:[save,gj('failed',5,{message:'boom'})]});
 assert.deepEqual(shape(stopped),['cant','bad','Can’t save','cant']);assert.equal(stopped.detail,'boom');assert.equal(stopped.code,'');
 const later=chip(bound,{git_jobs:[gj('failed',50),save]});assert.equal(later.key,'saved','a failed attempt older than the save ends nothing');
 for(const code of ['vm','account','busy','diverged','files','settings','devices','other']){const s=chip({...bound,git_status:{checked:true,ready:false,problem:'text',code}},{git_jobs:[save]});assert.equal(s.key,'cant',code);assert.equal(s.code,code);assert.equal(s.detail,'text');}
 assert.equal(chip({...bound,git_status:{checked:true,ready:false,problem:'',code:''}},{git_jobs:[save]}).code,'other');
 for(const status of [{checked:false,ready:false,code:'vm'},undefined])assert.equal(chip({...bound,git_status:status},{git_jobs:[save]}).key,'saved','an unchecked or missing status is not Can\'t save');
 const refused=chip(bound,{git_jobs:[save],refusal:{message:'No.',at:ago(1)}});assert.equal(refused.key,'cant');assert.equal(refused.detail,'No.');
 const oldRefusal=chip(bound,{git_jobs:[save],refusal:{message:'No.',at:ago(90)}});assert.equal(oldRefusal.key,'saved');
 assert.equal(chip(bound,{git_jobs:[save],refusal:{message:'No.'}}).key,'cant','a refusal without a time is the newest event');
 const withWaiting=chip({...bound,git_status:{checked:true,ready:false,code:'diverged'}},{git_jobs:[save,gj('review_pending',10)]});assert.equal(withWaiting.key,'cant');assert.equal(withWaiting.also.key,'waiting');
 const withFailed=chip({...bound,git_status:{checked:true,ready:false,code:'vm'}},{git_jobs:[gj('push_pending',10)]});assert.equal(withFailed.also.key,'failed');
 assert.equal(chip(unbound,{git_jobs:[save,gj('capture_incomplete',2)]}).key,'cant','a failed attempt needs no connection');
});

test('7.1 row 7 Upload failed: a waiting job is push_pending; the count is every waiting commit',()=>{
 const s=chip(bound,{git_jobs:[gj('push_pending',5),gj('review_pending',20)]});
 assert.deepEqual(shape(s),['failed','bad','Upload failed','failed']);assert.equal(s.count,2);assert.equal(s.job.status,'push_pending');
});

test('7.1 row 8 Waiting: one or more waiting jobs, counted by distinct commit; a dismissed job and an uploaded one do not count',()=>{
 const one=chip(bound,{git_jobs:[gj('review_pending',5)]});assert.deepEqual(shape(one),['waiting','warn','1 save to upload','upload']);
 for(const status of ['committed','review_pending'])assert.equal(chip(bound,{git_jobs:[gj(status,5)]}).count,1,status);
 assert.equal(chip(bound,{git_jobs:[gj('interrupted',5,{commit:'zz'})]}).text,'1 save to upload');
 const same=[gj('committed',5,{commit:'same'}),gj('review_pending',6,{commit:'same'})];assert.equal(chip(bound,{git_jobs:same}).count,1,'two jobs with one commit count once');
 assert.equal(chip(bound,{git_jobs:[gj('committed',5),gj('committed',6),gj('review_pending',7)]}).text,'3 saves to upload');
 assert.equal(chip(bound,{git_jobs:[gj('committed',5),gj('dismissed',9,{commit:'d'})]}).count,1,'a dismissed job does not count');
 assert.equal(chip(bound,{git_jobs:[gj('committed',5,{target:'move'})]}).text,'1 save to upload','a folder move counts');
 assert.equal(chip(bound,{git_jobs:[gj('committed',5,{kind:'design'})]}).text,'1 save to upload','a design export counts');
 assert.equal(chip(bound,{git_jobs:[gj('committed',5,{kind:'state'})]}).text,'1 save to upload','a lab state counts');
 assert.equal(chip(bound,{git_jobs:[gj('committed',5,{commit:''})]}).key,'none','a job without a commit is not a waiting save');
 assert.equal(chip(bound,{git_jobs:[gj('committed',5,{lab_id:'other'})]}).key,'none');
});

test('7.1 row 9 Saved: the newest capture save that changed something is uploaded, or the lab has only unchanged capture saves',()=>{
 const s=chip(bound,{git_jobs:[gj('synced',21)]});assert.deepEqual(shape(s),['saved','ok','Saved 21 min ago','rest']);
 const after=chip(bound,{git_jobs:[gj('synced',21),gj('unchanged',2)]});assert.equal(after.text,'Saved 21 min ago','an unchanged save keeps the earlier time');
 const only=chip(bound,{git_jobs:[gj('unchanged',7)]});assert.equal(only.key,'saved');assert.equal(only.text,'Saved 7 min ago');
 assert.equal(chip(unbound,{git_jobs:[gj('synced',21)]}).panel,'first','without a save location the chip opens the first-save view');
 assert.equal(chip(bound,{git_jobs:[gj('synced',5,{captured:undefined,target:'latest'})]}).key,'saved');
});

test('7.1 row 10 Kept and row 11 Not saved',()=>{
 const kept=chip(bound,{git_jobs:[gj('dismissed',5,{commit:'k'})]});assert.deepEqual(shape(kept),['kept','none','Kept on this VM','rest']);
 assert.equal(chip(bound,{git_jobs:[gj('dismissed',5,{commit:'k'}),gj('dismissed',9,{commit:'j'})]}).key,'kept');
 assert.equal(chip(bound,{git_jobs:[gj('dismissed',5,{commit:'k'}),gj('synced',9)]}).key,'saved','a save that was not put aside is the lab\'s save');
 assert.deepEqual(shape(chip(bound,{})),['none','none','Not saved yet','first']);assert.deepEqual(shape(chip(unbound,{})),['none','none','Not saved yet','first']);
 assert.equal(chip(bound,{git_jobs:[gj('synced',5,{lab_id:'other'})]}).key,'none','another lab is ignored');
 assert.equal(chip(null,{}).key,'none');assert.equal(chip(bound,{git_jobs:[gj('synced',5,{target:'update'})]}).key,'none','a repository update is not a save');
 assert.equal(chip(bound).key,'none','ctx is optional');
});

test('PROMPT 5.2: each of the nine chip states has its dot and its text, and the text always names the state',()=>{
 const rows=[
  ['Saved',bound,{git_jobs:[gj('synced',21)]},'ok','Saved 21 min ago'],
  ['Saving',bound,{git_jobs:[gj('capturing',0)]},'busy','Saving…'],
  ['Waiting',bound,{git_jobs:[gj('review_pending',5)]},'warn','1 save to upload'],
  ['Failed',bound,{git_jobs:[gj('push_pending',5)]},'bad','Upload failed'],
  ['Needs attention',{...bound,git_status:{checked:true,ready:false,code:'vm'}},{},'bad','Can’t save'],
  ['Not saved',bound,{},'none','Not saved yet'],
  ['Loading',bound,{restore_jobs:[rj('applying',0,[tg('a','verified'),tg('b','applying',{stage:'applying'})],{finished:''})]},'busy','Loading… 1 of 2'],
  ['Running',bound,{restore_jobs:[rj('succeeded',5,loaded4,{source:{type:'folder',path:'bgp/checkpoints/ospf-up'}})]},'info','Running ospf-up'],
  ['Partial',bound,{restore_jobs:[rj('partial',5,[tg('a','verified'),tg('b','failed')])]},'warn','Loaded 1 of 2']];
 for(const [name,lab,ctx,dot,text] of rows){const s=chip(lab,ctx);assert.equal(s.dot,dot,name);assert.equal(s.text,text,name);}
});

test('review K1: a load that changed nothing after a good one leaves the chip on the good one',()=>{
 const a=rj('succeeded',30,loaded4,{source:{type:'folder',path:'bgp/checkpoints/ospf-up'}});
 for(const b of [rj('failed',5,[tg('r1','failed'),tg('r2','ineligible')]),rj('preflight_failed',5,[]),rj('failed',5,[tg('r1','rolled_back')])]){
  const s=chip(bound,{restore_jobs:[a,b]});assert.equal(s.text,'Running ospf-up');assert.equal(s.load.job.id,a.id);
 }
 const b=rj('partial',5,[tg('r1','verified'),tg('r2','failed')]);const s=chip(bound,{restore_jobs:[a,b]});assert.equal(s.key,'partial');assert.equal(s.load.job.id,b.id);
});

test('review K2: only a capture save that read the devices ends Running; a checkpoint from a capture, a lab state, a design export, a move, an update and a failed attempt do not',()=>{
 const load=rj('succeeded',30,loaded4);
 for(const status of ['synced','unchanged','committed','review_pending','push_pending'])assert.notEqual(chip(bound,{restore_jobs:[load],git_jobs:[gj(status,5)]}).key,'running',status+' ends it');
 const keepsRunning=[gj('committed',5,{captured:false,target:'checkpoint'}),gj('committed',5,{kind:'state'}),gj('committed',5,{kind:'design'}),gj('committed',5,{target:'move',captured:false}),gj('synced',5,{target:'update',captured:false})];
 for(const job of keepsRunning)assert.equal(chip(bound,{restore_jobs:[load],git_jobs:[job]}).key,'running',JSON.stringify([job.target,job.kind,job.captured]));
 const afterCheckpoint=chip(bound,{restore_jobs:[load],git_jobs:[gj('review_pending',5,{captured:false,target:'checkpoint'})]});assert.equal(afterCheckpoint.key,'running');assert.equal(afterCheckpoint.also.key,'waiting');
 for(const status of ['export_pending','capture_incomplete','failed'])assert.equal(chip(bound,{restore_jobs:[load],git_jobs:[gj(status,5)]}).load.job.id,load.id,status+' ends nothing');
 assert.equal(chip(bound,{restore_jobs:[load],git_jobs:[gj('synced',50)]}).key,'running','a capture save older than the load ends nothing');
 assert.equal(chip(bound,{restore_jobs:[load],git_jobs:[gj('synced',5,{captured:undefined,target:'checkpoint'})]}).key,'running','a job stored before `captured` counts only when it wrote latest');
 assert.equal(chip(bound,{restore_jobs:[load],git_jobs:[gj('synced',5,{captured:undefined,target:'latest'})]}).key,'saved');
});

test('review K4: waiting saves count for a lab that is not connected',()=>{
 const s=chip(unbound,{git_jobs:[gj('review_pending',5)]});assert.deepEqual(shape(s),['waiting','warn','1 save to upload','upload']);assert.notEqual(s.text,'Not saved yet');
 assert.equal(chip(unbound,{git_jobs:[gj('push_pending',5)]}).key,'failed');
});

test('review K5: a lab state (kind state) never names Saved, never ends Running, and a lab with only one reads Not saved yet',()=>{
 const state=gj('synced',5,{kind:'state'});
 assert.equal(chip(bound,{git_jobs:[state]}).key,'none');assert.equal(chip(bound,{git_jobs:[gj('synced',60),state]}).text,'Saved 1 h ago');
 assert.equal(chip(bound,{restore_jobs:[rj('succeeded',30,loaded4)],git_jobs:[state]}).key,'running');
 const design=gj('synced',5,{kind:'design'});assert.equal(chip(bound,{git_jobs:[design]}).key,'none');assert.equal(chip(bound,{restore_jobs:[rj('succeeded',30,loaded4)],git_jobs:[design]}).key,'running');
 assert.equal(chip(bound,{git_jobs:[gj('committed',5,{kind:'state'})]}).job.kind,'state','its waiting row is the state\'s job, so Try again retries that job');
});

test('review K6: a finished deploy, redeploy, destroy or design apply of the lab newer than the load ends it; lab.last_deployed is the second source',()=>{
 const load=rj('succeeded',30,loaded4),save=gj('synced',90);
 const op=(action,min,extra={})=>({id:'o'+action+min,lab_id:'lab',action,status:'succeeded',created:ago(min+1),finished:ago(min),...extra});
 for(const action of ['deploy','redeploy','destroy']){const s=chip(bound,{restore_jobs:[load],git_jobs:[save],operations:[op(action,5)]});assert.equal(s.key,'saved',action);assert.equal(s.load,null);}
 assert.equal(chip(bound,{restore_jobs:[load],git_jobs:[save],operations:[op('deploy',5,{status:'failed'})]}).key,'saved','a failed redeploy may have restarted devices: it ends the load too');
 for(const other of [op('deploy',5,{lab_id:'other'}),op('deploy',60),op('deploy',5,{status:'running',finished:''}),op('restart',5),op('restart-node',5),op('save',5)])assert.equal(chip(bound,{restore_jobs:[load],git_jobs:[save],operations:[other]}).key,'running',JSON.stringify([other.lab_id,other.action,other.status]));
 const design=(extra={})=>({id:'d1',lab_id:'lab',status:'succeeded',created:ago(6),finished:ago(5),...extra});
 assert.equal(chip(bound,{restore_jobs:[load],git_jobs:[save],design_jobs:[design()]}).key,'saved');
 for(const other of [design({lab_id:'other'}),design({finished:ago(60),created:ago(61)}),design({status:'applying',finished:''}),design({status:'interrupted',rechecking:['r1']})])assert.equal(chip(bound,{restore_jobs:[load],git_jobs:[save],design_jobs:[other]}).key,'running');
 assert.equal(chip({...bound,last_deployed:ago(5)},{restore_jobs:[load],git_jobs:[save]}).key,'saved');
 assert.equal(chip({...bound,last_deployed:ago(60)},{restore_jobs:[load],git_jobs:[save]}).key,'running');
 const ended=makeContext().loadState({...bound,last_deployed:ago(5)},{restore_jobs:[load]},NOW);assert.equal(ended.key,'');assert.equal(ended.last.job.id,load.id,'`last` still names the load');
});

test('review O1: Loaded n of m counts verified devices only',()=>{
 const job=rj('partial',5,[tg('r1','verified'),tg('r2','verified'),tg('r3','verified'),tg('r4','applied_unverified')]);
 const c=makeContext();assert.equal(c.loadState(bound,{restore_jobs:[job]},NOW).loaded,3);assert.equal(chip(bound,{restore_jobs:[job]}).text,'Loaded 3 of 4');
 const counts=plain(c.loadCounts(rj('partial',5,[tg('a','verified'),tg('b','applied_unverified'),tg('c','verify_mismatch'),tg('d','failed'),tg('e','rolled_back'),tg('f','ineligible'),tg('g','uncertain',{stage:'uncertain'}),tg('h','verified',{stage:'matched'})])));
 assert.deepEqual(counts,{total:8,done:8,loaded:2,replaced:4,unverified:2,unknown:1,failed:1,rolledBack:1,skipped:1,interrupted:0,matched:1});
});

test('review O2: a device is unknown only when its stage is uncertain or it still awaits its read-back',()=>{
 const c=makeContext();
 const before=rj('failed',5,[tg('r1','failed'),tg('r2','interrupted',{stage:'failed',timeline:{queued:1,settled:2}}),tg('r3','interrupted',{stage:'failed',timeline:{queued:1,settled:2}}),tg('r4','failed')]);
 const s=c.loadState(bound,{restore_jobs:[before]},NOW);assert.equal(s.key,'');assert.equal(s.undo.available,false);assert.equal(s.last,null);assert.notEqual(chip(bound,{restore_jobs:[before]}).text,'Loaded 0 of 4');
 const uncertain=rj('needs_attention',5,[tg('r1','failed'),tg('r2','uncertain',{stage:'uncertain'})]);assert.equal(chip(bound,{restore_jobs:[uncertain]}).text,'Loaded 0 of 2');
 const reading=rj('interrupted',5,[tg('r1','failed'),tg('r2','interrupted',{stage:'applying',timeline:{queued:1}})]);assert.equal(chip(bound,{restore_jobs:[reading]}).key,'partial','an interrupted device whose timeline has no settled entry awaits its read-back');
 const oldJob=rj('interrupted',5,[tg('r1','interrupted',{stage:'applying'})]);assert.equal(chip(bound,{restore_jobs:[oldJob]}).key,'none','a job stored before stages existed has no timeline and is not counted');
});

test('review O4: the name after Running is the save whose capture is the loaded state\'s, else an earlier save with its time',()=>{
 const own={type:'folder',path:'bgp/latest',commit:'head-of-checkout',capture_id:'cap-7'};
 const saves=[gj('synced',300,{id:'s1',backup_job_id:'cap-3',note:'old one'}),gj('synced',200,{id:'s2',backup_job_id:'cap-7',note:'ospf fixed'}),gj('synced',100,{id:'s3',backup_job_id:'cap-9',note:'newest'})];
 const run=(source,extra={})=>chip(bound,{restore_jobs:[rj('succeeded',5,loaded4,{source})],git_jobs:saves,...extra}).text;
 assert.equal(run(own),'Running ospf fixed');
 assert.equal(run({...own,commit:'whatever'}),'Running ospf fixed','the commit cannot tell: the capture does');
 assert.equal(run({...own,capture_id:'cap-1'},{states:[{path:'bgp/latest',saved_at:ago(2*1440)}]}),'Running an earlier save, 2 days ago','never the newest save\'s name for another capture');
 assert.equal(run({...own,capture_id:''}),'Running an earlier save');
 const renamed=saves.map(j=>j.id==='s2'?{...j,note:'renamed'}:j);assert.equal(chip(bound,{restore_jobs:[rj('succeeded',5,loaded4,{source:own})],git_jobs:renamed}).text,'Running renamed','a renamed save shows its current name');
 const noNote=[gj('synced',100,{id:'s4',backup_job_id:'cap-7',note:''})];assert.equal(chip(bound,{restore_jobs:[rj('succeeded',5,loaded4,{source:own})],git_jobs:noNote}).text,'Running your latest save');
 assert.equal(run({type:'folder',path:'/bgp/checkpoints/before-bgp',commit:'x'}),'Running before-bgp');
 assert.equal(run({type:'folder',path:'bgp/baseline',commit:'x'}),'Running your starting point');
 assert.equal(run({type:'folder',path:'course/bgp/start/latest',commit:'x'},{states:[{path:'course/bgp/start/latest',name:'Start · BGP'}]}),'Running Start · BGP','a lab state by its name from the list');
 assert.equal(run({type:'folder',path:'course/bgp/start/latest',commit:'x'}),'Running Start','without the list the same rule gives the name');
 assert.equal(run({type:'git',path:'/other/work',commit:'x'}),'Running Work');
 assert.equal(chip(unbound,{restore_jobs:[rj('succeeded',5,loaded4,{source:{type:'folder',path:'bgp/latest',commit:'x'}})]}).text,'Running Bgp','a lab without a save location has no own folder: the state is named like any other');
});

test('review U3: the backup before a load of X reads "the configuration from before X"; the undo of an undo of X reads X',()=>{
 const c=makeContext();
 const y={id:'ry',lab_id:'lab',status:'succeeded',created:ago(300),finished:ago(299),source:{type:'folder',path:'bgp/checkpoints/ospf-up'},targets:loaded4,pre_backup_job_id:'b0'};
 const undoY={id:'rx',lab_id:'lab',status:'succeeded',created:ago(200),finished:ago(199),source:{type:'backup',backup_job_id:'b0'},targets:loaded4,pre_backup_job_id:'b1'};
 const jobs=[{id:'b0',source:'restore-pre',progress_id:'ry',finished:ago(300)},{id:'b1',source:'restore-pre',progress_id:'rx',finished:ago(200)},{id:'plain',source:'',finished:ago(1500)}];
 const name=(source,restore_jobs)=>c.loadSourceName(source,{jobs,restore_jobs,git_jobs:[]},bound,NOW);
 assert.equal(name({type:'backup',backup_job_id:'b0'},[y,undoY]),'the configuration from before ospf-up');
 assert.equal(name({type:'backup',backup_job_id:'b1'},[y,undoY]),'ospf-up','undoing an undo of X reads X');
 assert.equal(name({type:'backup',backup_job_id:'plain'},[y]),'a backup from 1 day ago'.replace('1 day ago','yesterday'));
 assert.equal(name({type:'backup',backup_job_id:'gone'},[y]),'a backup');
 const chipText=chip(bound,{restore_jobs:[y,undoY,rj('succeeded',5,loaded4,{source:{type:'backup',backup_job_id:'b1'}})],jobs,git_jobs:[]}).text;assert.equal(chipText,'Running ospf-up');
});

test('the load state: effective loads, last, undo and the loading fields',()=>{
 const c=makeContext(),load=rj('succeeded',10,loaded4,{pre_backup_job_id:'b9',source:{type:'folder',path:'bgp/baseline'}});
 const s=c.loadState(bound,{restore_jobs:[load],jobs:[{id:'b9'}]},NOW);
 assert.equal(s.key,'running');assert.equal(s.name,'your starting point');assert.equal(s.loaded,4);assert.equal(s.total,4);assert.equal(s.done,4);assert.equal(s.undo.available,true);assert.equal(s.undo.reason,'');assert.equal(s.last.job.id,load.id);assert.equal(s.last.key,'running');
 const gone=c.loadState(bound,{restore_jobs:[load],jobs:[]},NOW);assert.equal(gone.undo.available,false);assert.equal(gone.undo.reason,'The automatic backup of this load is no longer kept.');
 assert.equal(c.loadState(bound,{restore_jobs:[{...load,pre_backup_job_id:''}],jobs:[]},NOW).undo.reason,'');
 const after=c.loadState(bound,{restore_jobs:[load],git_jobs:[gj('synced',2)]},NOW);assert.equal(after.key,'');assert.equal(after.last.job.id,load.id,'`last` outlives the chip state');assert.equal(after.undo.available,false);
 assert.equal(c.loadState(null,{},NOW).key,'');assert.equal(c.loadState(bound,{},NOW).last,null);
 const newer=rj('succeeded',2,loaded4,{id:'newest'});assert.equal(c.loadState(bound,{restore_jobs:[load,newer]},NOW).job.id,'newest','the newest effective load wins');
});

test('loadDeviceWord: every word of LOAD.md 5.1, from the service\'s status and stage only',()=>{
 const c=makeContext(),w=(t,job)=>plain(c.loadDeviceWord(t,job));
 assert.deepEqual(w({status:'verified',stage:'replaced'}),{text:'Loaded',cls:'ok',final:true,help:''});
 assert.deepEqual(w({status:'verified',stage:'matched'}),{text:'Already matched',cls:'ok',final:true,help:''});
 assert.deepEqual(w({status:'applied',stage:'matched'}),{text:'Already matched',cls:'ok',final:true,help:''});
 assert.deepEqual(w({status:'applied',stage:'checking'}),{text:'Loading…',cls:'now',final:false,help:''},'replaced and still under the follow-up check is never Loaded');
 assert.deepEqual(w({status:'applied_unverified'}),{text:'Loaded, not verified',cls:'warn',final:true,help:''});
 assert.deepEqual(w({status:'verify_mismatch'}),{text:'Loaded, differences remain',cls:'warn',final:true,help:''});
 assert.deepEqual(w({status:'failed',message:'Configuration was not changed. The device rejected the configuration.'}),{text:'Not loaded',cls:'bad',final:true,help:'The device rejected the configuration.'});
 assert.equal(w({status:'failed',message:'Connectivity: probe failed'}).help,'The device did not answer over SSH.');
 assert.deepEqual(w({status:'ineligible',message:'x'}),{text:'Skipped',cls:'',final:true,help:''});
 assert.deepEqual(w({status:'rolled_back'}),{text:'Kept previous',cls:'bad',final:true,help:'Undid the change; its previous configuration was read back.'});
 assert.deepEqual(w({status:'uncertain',stage:'uncertain'}),{text:'Not confirmed',cls:'warn',final:true,help:'The manager could not confirm what this device runs. Open Details.'});
 assert.deepEqual(w({status:'interrupted',stage:'failed',timeline:{settled:2}},{status:'interrupted'}),{text:'Interrupted',cls:'warn',final:true,help:'Open Details.'});
 assert.deepEqual(w({status:'rollback_expected'}),{text:'Not confirmed',cls:'warn',final:true,help:'Open Details.'});
 assert.deepEqual(w({status:'interrupted',stage:'applying',timeline:{queued:1}},{status:'interrupted',rechecking:true}),{text:'Checking…',cls:'now',final:false,help:''});
 assert.equal(w({status:'interrupted',stage:'applying',timeline:{queued:1}},{status:'interrupted',rechecking:false}).text,'Interrupted','without rechecking the job is finished');
 assert.equal(w({status:'pending',stage:'queued'}).text,'Waiting');assert.equal(w({status:'pending'}).text,'Waiting','an old job without stages');
 for(const stage of ['backing_up','backed_up'])assert.deepEqual(w({status:'backing_up',stage}),{text:'Backing up…',cls:'now',final:false,help:''});
 for(const stage of ['connecting','applying','armed','verifying','confirming','checking'])assert.equal(w({status:'applying',stage}).text,'Loading…',stage);
 // Kept previous is produced for rolled_back and nothing else; uncertain, interrupted and rollback_expected never read Loaded and carry Details.
 for(const status of ['verified','applied','applied_unverified','verify_mismatch','failed','ineligible','uncertain','interrupted','rollback_expected','pending','applying','backing_up','confirming'])
  if(status!=='rolled_back')assert.notEqual(w({status,stage:'x'}).text,'Kept previous',status);
 for(const status of ['uncertain','interrupted','rollback_expected']){const word=w({status,stage:'failed',timeline:{settled:1}});assert.doesNotMatch(word.text,/^Loaded/);assert.match(word.help,/Open Details\./);}
 assert.equal(w({status:'brand-new'}).text,'Not confirmed','an unknown status is never worded as an outcome it did not report');
 const table=vm.runInContext('STATUS_LOAD_WORDS',c);
 for(const key of ['verified','applied','matched','applied_unverified','verify_mismatch','ineligible','failed','rolled_back','uncertain','interrupted','rollback_expected'])assert.ok(table[key],'STATUS_LOAD_WORDS has '+key);
 const outcomes=['verified','applied','matched','applied_unverified','verify_mismatch','ineligible','failed','rolled_back','uncertain','interrupted','rollback_expected'];
 const restoreJs=fs.readFileSync(path.join(__dirname,'../app/static/restore.js'),'utf8'),block=restoreJs.slice(restoreJs.indexOf('const restoreOutcomes'),restoreJs.indexOf('let restoreWatch'));
 for(const key of [...block.matchAll(/(\w+):\s*\['/g)].map(m=>m[1]))assert.ok(outcomes.includes(key),'every key of restoreOutcomes is covered: '+key);
});

test('loadSourceName and loadState need no ctx fields to be present',()=>{
 const c=makeContext();
 assert.equal(c.loadSourceName(undefined,undefined,undefined,NOW),'a saved state');
 assert.equal(c.loadSourceName({type:'folder',path:'a/b/final/latest'},{},null,NOW),'Final');
 assert.equal(c.loadSourceName({type:'backup',backup_job_id:'x'},{},bound,NOW),'a backup');
 assert.equal(c.loadSourceName({type:'folder',path:'bgp/latest'},{lab:bound},undefined,NOW),'an earlier save','the lab may ride in ctx.lab');
});

test('integration: the time of a save is when it read the devices, so an upload after a load does not end Running',()=>{
 const load=rj('succeeded',30,loaded4);
 // Saved 60 minutes ago, loaded 30 minutes ago, uploaded 5 minutes ago: `finished` moved with the upload, the capture did not.
 const uploaded={...gj('synced',60),finished:ago(5)};
 const s=chip(bound,{restore_jobs:[load],git_jobs:[uploaded]});assert.equal(s.key,'running');assert.equal(s.text,'Running ospf-up');
 // A save made after the load ends it, whenever it is uploaded.
 assert.equal(chip(bound,{restore_jobs:[load],git_jobs:[{...gj('synced',10),finished:ago(1)}]}).key,'saved');
 // The newest save is the one created last, not the one whose upload ended last.
 const older={...gj('synced',60,{note:'older'}),finished:ago(1)},newer={...gj('synced',20,{note:'newer'}),finished:ago(19)};
 assert.equal(chip(bound,{git_jobs:[older,newer]}).job.note,'newer');
});
test('integration: a lab without a save location whose placement the VM refused says why (PROMPT 6.5)',()=>{
 const c=makeContext(),refusedFor=code=>({...unbound,git_status:{checked:true,ready:false,problem:'raw sentence of the VM',code,waiting:0}});
 let s=chip(refusedFor('busy'));assert.equal(s.key,'cant');assert.equal(s.code,'busy');assert.equal(s.panel,'cant');
 let p=plain(c.saveProblem(refusedFor('busy'),{}));assert.equal(p.sentence,'Someone is working in this repository on the VM.');assert.equal(p.detail,'raw sentence of the VM');
 p=plain(c.saveProblem(refusedFor('diverged'),{}));assert.equal(p.sentence,'The online copy has changes this VM does not have.');
 p=plain(c.saveProblem(refusedFor('vm'),{}));assert.equal(p.sentence,'The lab VM could not be reached.');
 // A refusal without a cause the page can word leaves the first-save panel with the manager's own sentence.
 s=chip(refusedFor('other'));assert.equal(s.key,'none');assert.equal(s.panel,'first');
 assert.equal(chip({...unbound,git_status:{checked:'',ready:null,problem:'',code:'',waiting:0}}).key,'none');
});
test('DESIGN.md 3.6: Can\'t save sentence and actions for each code',()=>{
 const c=makeContext(),problem=(lab,ctx={})=>plain(c.saveProblem(lab,ctx)),acts=p=>p.actions.map(a=>a.label).join(' | '),ids=p=>p.actions.map(a=>a.action).join(',');
 const st=(code,extra={})=>({...bound,git_status:{checked:true,ready:false,problem:'raw',code,waiting:0,...extra}});
 let p=problem(st('vm'));assert.equal(p.sentence,'The lab VM could not be reached.');assert.equal(acts(p),'Try again | Check the VM connection…');assert.equal(ids(p),'again,vm');
 p=problem(st('account'));assert.equal(p.sentence,'The VM account cannot upload to github.com.');assert.equal(acts(p),'Try again | Details');
 assert.equal(problem({...st('account'),git_binding:{repository:{}}}).sentence,'The VM account cannot upload to the online repository.');
 p=problem(st('busy'));assert.equal(p.sentence,'Someone is working in this repository on the VM.');assert.equal(acts(p),'Try again | Details');
 p=problem(st('diverged'));assert.equal(p.sentence,'The online copy has changes this VM does not have.');assert.equal(acts(p),'Update from the repository');assert.equal(ids(p),'update');
 p=problem(st('diverged',{waiting:1}));assert.equal(p.sentence,'The online copy and this VM both have changes the other does not have. They have to be combined on the VM.');assert.equal(acts(p),'Try again | Details','no Update while a save waits; Try again uploads the waiting saves once the owner has combined both sides');assert.equal(ids(p),'upload-again,details');
 assert.deepEqual(p.commands,['git -C /srv/repo pull --no-rebase','git -C /srv/repo push'],'what the repository’s owner runs on the VM, with the lab’s checkout path');
 assert.deepEqual(problem(st('diverged')).commands,[]);assert.deepEqual(problem(st('busy')).commands,[]);
 const waitingJob=gj('review_pending',5,{destination:{checkout:'/srv/repo'}});
 assert.equal(problem(st('diverged'),{git_jobs:[waitingJob]}).actions[0].action,'upload-again','a waiting save of any lab in the lab\'s checkout');
 assert.equal(problem(st('diverged'),{git_jobs:[{...waitingJob,destination:{checkout:'/srv/other'}}]}).actions[0].action,'update');
 assert.equal(problem(st('diverged'),{git_jobs:[{...waitingJob,pushed:true}]}).actions[0].action,'update');
 p=problem(st('files'));assert.equal(p.sentence,'bgp holds files that were not saved by the manager.');assert.equal(acts(p),'Choose another place | Details');
 assert.equal(problem({...st('files'),git_binding:{repository:{prefix:''}}}).sentence,'The top level holds files that were not saved by the manager.');
 // `settings` is the backend's code for a save location that has to be set up again (the VM's record or checkout is gone or changed);
 // Details carries the VM's own sentence. `devices` is the empty device selection (seam 11 of the integration, a ruling of the lead).
 p=problem(st('settings'));assert.equal(p.code,'settings');assert.equal(p.sentence,'This lab’s save location has to be set up again.');assert.equal(acts(p),'Save settings | Details');assert.equal(p.actions[0].action,'settings');
 p=problem(st('devices'));assert.equal(p.code,'devices');assert.equal(p.sentence,'No device of this lab is selected for saving.');assert.equal(acts(p),'Save settings');assert.equal(p.actions[0].action,'settings');
 for(const code of ['other','','nonsense']){p=problem(st(code));assert.equal(p.sentence,'The save did not work.',code);assert.equal(acts(p),'Try again | Details');assert.equal(p.code,'other');}
 assert.equal(problem(bound).code,'other','a refusal or a failed job with no status is the fallback');
 // A device that could not be read, from the backup job the stopped save made.
 const stopped=gj('capture_incomplete',5,{backup_job_id:'bk',message:'A device could not be read.'});
 const backup=nodes=>({id:'bk',nodes});
 const lab={...bound,nodes:[{name:'clab-bgp-ceos',short_name:'ceos'},{name:'clab-bgp-xrv9k',short_name:'xrv9k'},{name:'clab-bgp-cj',short_name:'cj'}]};
 p=problem(lab,{git_jobs:[stopped],jobs:[backup([{name:'clab-bgp-ceos',status:'failed'},{name:'clab-bgp-cj',status:'succeeded'}])]});
 assert.equal(p.code,'device');assert.equal(p.sentence,'ceos could not be read, so nothing was saved.');assert.equal(acts(p),'Try again | Save settings | Details');assert.equal(p.job.id,stopped.id);
 p=problem(lab,{git_jobs:[stopped],jobs:[backup([{name:'clab-bgp-ceos',status:'failed'},{name:'clab-bgp-xrv9k',status:'timeout'}])]});assert.equal(p.sentence,'ceos and xrv9k could not be read, so nothing was saved.');
 p=problem(lab,{git_jobs:[stopped],jobs:[]});assert.equal(p.sentence,'A device could not be read, so nothing was saved.');
 // A save the manager stopped for its own reason (no device failed: the topology could not be saved with the capture, the capture
 // does not hold the devices) shows the manager's sentence as it is, with Try again and Details: never the device sentence (seam 16).
 const whole=gj('capture_incomplete',5,{backup_job_id:'bk',message:'The topology could not be saved with this capture. Try again.'});
 p=problem(lab,{git_jobs:[whole],jobs:[backup([{name:'clab-bgp-ceos',status:'succeeded'},{name:'clab-bgp-cj',status:'succeeded'}])]});
 assert.equal(p.code,'capture');assert.equal(p.sentence,'The topology could not be saved with this capture. Try again.');assert.equal(acts(p),'Try again | Details');assert.deepEqual(p.devices,[]);assert.equal(p.job.id,whole.id);
 p=problem(lab,{git_jobs:[whole],jobs:[]});assert.equal(p.code,'device','a capture that is gone keeps the device sentence');
 p=problem(lab,{git_jobs:[stopped],jobs:[backup([{name:'clab-bgp-ceos',status:'failed'}])],refusal:{message:'No.',at:ago(1)}});assert.equal(p.code,'other','a refusal newer than the stopped job is the cause');assert.equal(p.detail,'No.');
 assert.equal(problem(st('vm'),{git_jobs:[stopped],jobs:[backup([{name:'clab-bgp-ceos',status:'failed'}])]}).code,'device','a job that stopped on a device is found first');
 assert.equal(problem(bound,{git_jobs:[gj('export_pending',2)]}).code,'other');
 assert.equal(problem(null,{}).code,'other','no lab does not throw');
});

test('PROMPT 5.2 table: relativeTimeShort at each threshold',()=>{
 const c=makeContext(),at=ms=>c.relativeTimeShort(NOW-ms,NOW),min=60000,hour=3600000,day=86400000;
 assert.equal(at(0),'just now');assert.equal(at(44999),'just now');assert.equal(at(45000),'1 min ago');assert.equal(at(90000),'2 min ago');
 assert.equal(at(21*min),'21 min ago');assert.equal(at(59*min),'59 min ago');assert.equal(at(59.6*min),'59 min ago','never "60 min ago"');assert.equal(at(hour),'1 h ago');
 assert.equal(at(2*hour),'2 h ago');assert.equal(at(23.7*hour),'23 h ago');assert.equal(at(day),'yesterday');assert.equal(at(47*hour),'yesterday');
 assert.equal(at(2*day),'2 days ago');assert.equal(at(3*day),'3 days ago');assert.equal(at(6.9*day),'6 days ago','never "7 days ago"');
 const old=Date.parse('2026-09-04T12:00:00Z');assert.match(c.relativeTimeShort(old,NOW),/^[34] Sep$/,'seven days and more read as a calendar date, day first');
 assert.equal(c.relativeTimeShort(Date.parse('2026-08-29T12:00:00Z'),NOW),'29 Aug');
 assert.match(c.relativeTimeShort(Date.parse('2025-08-29T12:00:00Z'),NOW),/^29 Aug 2025$/,'a date about a year old names its year');
 assert.equal(c.relativeTimeShort(NOW+5*min,NOW),'just now','a time ahead of now never goes negative');
 assert.equal(c.relativeTimeShort(ago(21),NOW),'21 min ago','ISO strings');assert.equal(c.relativeTimeShort(Math.floor((NOW-3*hour)/1000),NOW),'3 h ago','Unix seconds');
 for(const bad of ['','not a date',null,undefined,0])assert.equal(c.relativeTimeShort(bad,NOW),'',String(bad));
 assert.doesNotMatch(c.relativeTimeShort('x',NOW)+c.relativeTimeShort(undefined,NOW),/NaN/);
});

test('savedVersionName: the last folder once a trailing latest is dropped, upper-cased only when all lower case',()=>{
 const c=makeContext();
 assert.equal(c.savedVersionName('start'),'Start');assert.equal(c.savedVersionName('broken-2'),'Broken-2');assert.equal(c.savedVersionName('BGP'),'BGP');
 assert.equal(c.savedVersionName('Final/latest'),'Final');assert.equal(c.savedVersionName('course/bgp/start/latest'),'Start');assert.equal(c.savedVersionName('course/bgp/start/latest/'),'Start');
 assert.equal(c.savedVersionName('latest'),'','the top level has no name');assert.equal(c.savedVersionName(''),'');assert.equal(c.savedVersionName('/'),'');assert.equal(c.savedVersionName(null),'');assert.equal(c.savedVersionName(undefined),'');
 assert.equal(c.savedVersionName('a/latest/working'),'Working','a latest in the middle is an ordinary name');assert.equal(c.savedVersionName('bgp/checkpoints/ospf-up'),'Ospf-up');
 assert.equal(c.savedVersionName('Mixed-Case'),'Mixed-Case');assert.equal(c.savedVersionName('2nd'),'2nd');
 assert.doesNotMatch(['solution','final','base','initial','broken_1'].map(n=>c.savedVersionName(n)).join(' '),/instructor|Starting state|Troubleshooting/,'the old special cases are gone');
});

test('PROMPT 5.3 step 3: the sentence of a save in every form',()=>{
 const c=makeContext(),s=(summary,also,job)=>c.saveChangeSentence(plain(summary??null)===null?null:summary,also,job);
 const one={devices:['ceos'],added:3,removed:0},two={devices:['ceos','xrv9k'],added:19,removed:1};
 assert.equal(s(two),'2 devices changed since your last save: ceos and xrv9k. 19 lines added, 1 removed.');
 assert.equal(s(one),'1 device changed since your last save: ceos. 3 lines added, 0 removed.');
 assert.equal(s({devices:['ceos'],added:1,removed:1}),'1 device changed since your last save: ceos. 1 line added, 1 removed.');
 assert.equal(s({devices:['ceos','cjunos','xrv9k'],added:5,removed:2}),'3 devices changed since your last save: ceos, cjunos and xrv9k. 5 lines added, 2 removed.');
 assert.equal(s({devices:['a','b','c','d'],added:1,removed:2}),'4 devices changed since your last save: a, b, c and d. 1 line added, 2 removed.');
 assert.equal(s({devices:['ceos','r1','r2','r3','r4','r5'],added:9,removed:4}),'6 devices changed since your last save: ceos, r1, r2 and 3 more. 9 lines added, 4 removed.');
 assert.equal(s({devices:['ceos'],added:3,removed:0,topology:true}),'1 device changed since your last save: ceos. 3 lines added, 0 removed. The topology changed.');
 assert.equal(s({...two,topology:true,map:true}),'2 devices changed since your last save: ceos and xrv9k. 19 lines added, 1 removed. The topology and the map changed.');
 assert.equal(s({...two,map:true}),'2 devices changed since your last save: ceos and xrv9k. 19 lines added, 1 removed. The map changed.');
 assert.equal(s({devices:[],map:true}),'The map changed since your last save.');assert.equal(s({devices:[],topology:true}),'The topology changed since your last save.');
 assert.equal(s({devices:[],topology:true,map:true}),'The topology and the map changed since your last save.');
 assert.equal(s({...two,removed_devices:['r9']}),'2 devices changed since your last save: ceos and xrv9k. 19 lines added, 1 removed. r9 is no longer saved; its file was removed.');
 assert.equal(s({devices:[],removed_devices:['r8','r9']}),'r8 and r9 are no longer saved; their files were removed.');
 assert.equal(s({first:true,devices:['a','b','c','d'],topology:true,map:true}),'This is the first save here: 4 devices, the topology and the map.');
 assert.equal(s({first:true,devices:['a']}),'This is the first save here: 1 device.');assert.equal(s({first:true,devices:[]}),'This is the first save here.');
 assert.equal(s({devices:[],added:0,removed:0}),'Nothing changed since your last save, which is not uploaded yet.');
 for(const none of [null,undefined,'x',[]])assert.equal(c.saveChangeSentence(none),'This save is on the lab VM and not uploaded yet.');
 assert.equal(s({devices:['ceos']}),'1 device changed since your last save: ceos.','no counts known, none shown');
 // The other saves the upload also sends.
 const row=(name,lab)=>({job_id:'j-'+name,lab,name,kind:'',target:'latest'});
 assert.equal(s(two,[row('Start','bgp')]),'2 devices changed since your last save: ceos and xrv9k. 19 lines added, 1 removed. This upload also sends 1 other save: Start (bgp).');
 assert.equal(s(one,[row('Start','bgp'),row('ospf fixed','ospf-lab'),{commit:'abc',name:'Save r1: first save',files:['r1.cfg']}]),'1 device changed since your last save: ceos. 3 lines added, 0 removed. This upload also sends 3 other saves: Start (bgp), ospf fixed (ospf-lab) and "Save r1: first save".');
 assert.equal(s(one,[row('a','l1'),row('b','l2')]),'1 device changed since your last save: ceos. 3 lines added, 0 removed. This upload also sends 2 other saves: a (l1) and b (l2).');
 const seven=[1,2,3,4,5,6,7].map(n=>row('s'+n,'lab'+n));assert.match(s(one,seven),/This upload also sends 7 other saves: s1 \(lab1\), s2 \(lab2\), s3 \(lab3\) and 4 more\.$/);
 assert.match(s(one,[{commit:'abc',name:'Save bgp: ceos changed',files:[]}]),/This upload also sends 1 other save: "Save bgp: ceos changed"\.$/,'a commit the manager no longer holds is named by its subject in quotes, without a lab');
 assert.match(s(one,[{job_id:'j',lab:{id:'l',name:'ospf-lab'},name:'Kept',kind:'',target:'latest'}]),/Kept \(ospf-lab\)\.$/);
 assert.match(s(one,[{job_id:'j',lab:'bgp',name:''}]),/Unnamed save \(bgp\)\.$/);
 assert.equal(s(null,[row('Start','bgp')]),'This save is on the lab VM and not uploaded yet. This upload also sends 1 other save: Start (bgp).');
 assert.equal(s(one,[]),s(one),'an empty list adds nothing');assert.equal(s(one,undefined),s(one));
 // The first sentence of a checkpoint and of a folder move is chosen by the job.
 assert.equal(s(two,[],{target:'checkpoint',checkpoint:'ospf-up'}),'Checkpoint ospf-up kept. It is not uploaded yet.');
 assert.equal(s(null,[],{target:'move',lab_name:'bgp',destination:{path:'course/bgp'}}),'bgp’s saved files moved to course/bgp.');
 assert.equal(s(null,[],{target:'move',lab_name:'bgp',destination:{path:''}}),'bgp’s saved files moved to the top level.');
 assert.equal(s(two,[],{target:'latest'}),s(two));
});

test('the restore words that LOAD.md 10 rewords, and the whole file stays pure',()=>{
 const c=makeContext(),job=(status)=>({id:'rs',lab_id:'lab',status,created:'2026-09-16T11:30:00Z',finished:'2026-09-16T11:31:00Z'});
 assert.equal(c.labState(running,{restore_jobs:[job('needs_attention')]}).detail,'The load needs a check on some devices.');
 assert.equal(c.labState(running,{restore_jobs:[job('partial')]}).detail,'The load finished on some devices only.');
 const source=fs.readFileSync(path.join(__dirname,'../app/static/status.js'),'utf8');
 assert.doesNotMatch(source.replace(/\/\/.*$/gm,''),/\b(document\.|window\.|localStorage|sessionStorage|addEventListener|location\.|history\.)/,'status.js touches no DOM, no listener and no storage');
 assert.doesNotMatch(source,/\bstyle=|\.innerHTML/);
});
test('S11-3 (C-025) loadState.recent is the lab’s newest finished load, also one that changed no device; the chip does not change for it',()=>{
 const c=makeContext(),ls=(lab,ctx)=>c.loadState(lab,ctx,NOW);
 assert.equal(plain(ls(bound,{})).recent,null);
 const none=rj('failed',5,[tg('r1','failed')]),effective=rj('succeeded',30,loaded4);
 let s=ls(bound,{restore_jobs:[none]});assert.equal(s.key,'');assert.equal(s.last,null);assert.equal(s.recent.job.id,none.id);assert.equal(s.recent.changed,false);assert.equal(s.recent.name,'ospf-up');
 s=ls(bound,{restore_jobs:[effective,none]});assert.equal(s.key,'running','an older effective load still describes the devices');assert.equal(s.recent.job.id,none.id);assert.equal(s.last.job.id,effective.id);
 s=ls(bound,{restore_jobs:[effective]});assert.equal(s.recent.job.id,effective.id);assert.equal(s.recent.changed,true);
 const active={...rj('applying',0,[tg('r1','pending')]),finished:''};
 s=ls(bound,{restore_jobs:[active,none]});assert.equal(s.key,'loading');assert.equal(s.recent.job.id,none.id,'a running load is not a finished one');
 assert.equal(chip(bound,{restore_jobs:[none],git_jobs:[gj('synced',60)]}).key,'saved');
});

test('a save written over a newer save the online copy held says so at the end of the upload sentence (risk review 4, finding 1)',()=>{
 const c=makeContext(),one={devices:['ceos'],added:3,removed:0},end=' The online copy held a newer save of this lab. This save replaces it.';
 const plainSentence=c.saveChangeSentence(one,null,{target:'latest'});
 assert.equal(plainSentence,'1 device changed since your last save: ceos. 3 lines added, 0 removed.');
 assert.equal(c.saveChangeSentence(one,null,{target:'latest',replaces_online:true}),plainSentence+end);
 const also=[{job_id:'j2',lab:'other-lab',name:'OSPF done'}];
 assert.equal(c.saveChangeSentence(one,also,{target:'latest',replaces_online:true}),c.saveChangeSentence(one,also,{target:'latest'})+end,'after everything else the upload sends');
 for(const job of [undefined,{target:'latest'},{target:'latest',replaces_online:false},{target:'latest',replaces_online:'yes'}])assert.doesNotMatch(c.saveChangeSentence(one,null,job),/online copy/);
});
