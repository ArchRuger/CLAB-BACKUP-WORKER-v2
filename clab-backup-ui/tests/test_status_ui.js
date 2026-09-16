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
 assert.equal(restore.label,'Replacing configuration');assert.equal(restore.pill,'busy');assert.equal(restore.job.id,'r1');
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
 assert.equal(restore.label,'Needs attention');assert.equal(restore.detail,'Replacing configuration did not finish.');assert.equal(restore.job.id,'rs-1');
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
 const failed=c.deviceState({name:'R3',ssh_ready:false,login_configured:true,nos_login:{status:'failed'}});
 assert.equal(failed.label,'Needs attention');assert.match(failed.detail,/R3 is running, but SSH login failed/);assert.equal(failed.next,'Check credentials');assert.equal(failed.pill,'danger');
 const down=c.deviceState({name:'R4',ssh_ready:false,available:false,nos_login:{status:'unavailable'}});
 assert.equal(down.label,'Unavailable');assert.equal(down.next,'Start lab');assert.equal(down.detail,'R4 is not running, or the lab status is out of date.');
 const creds=c.deviceState({name:'R5',ssh_ready:false,login_configured:false,nos_login:{status:'needs_credentials'}});
 assert.equal(creds.label,'Needs credentials');assert.equal(creds.next,'Add credentials');
 assert.equal(c.deviceState({name:'R6',ssh_ready:false,platform:'',readiness:'Choose NOS'}).label,'Choose network OS');
 const manual=c.deviceState({name:'R7',ssh_ready:true,nos_login:{status:'unmonitored'}});
 assert.equal(manual.label,'Ready');assert.equal(manual.detail,'Connected with the saved address.');assert.equal(manual.cli,true);
 assert.equal(c.deviceState(null).cli,false);
 for(const n of [ready,booting,failed,down,creds,manual])assert.ok(PILLS.includes(n.pill),n.label);
 assert.doesNotMatch(JSON.stringify([ready,booting,failed,down,creds,manual]),/router|stale|Not connected/i);
});

test('progress reads Not saved yet, Saving, Saved to Git, Saved on this VM or Needs attention',()=>{
 const c=makeContext(),lab={id:'lab',git_binding:{binding_id:'b'}};
 const none=c.progressState({id:'lab'},[]);
 assert.equal(none.label,'No save location yet');assert.equal(none.key,'unconnected');assert.match(none.detail,/Choose where this lab’s progress is saved/);
 assert.equal(c.progressState(lab,[]).label,'Not saved yet');
 const job=(status,extra={})=>({id:status,lab_id:'lab',status,target:'latest',created:'2026-09-16T11:48:00Z',finished:'2026-09-16T11:48:30Z',...extra});
 const synced=c.progressState(lab,[job('synced')],NOW);
 assert.equal(synced.label,'Saved to Git');assert.equal(synced.detail,'Saved 12 minutes ago.');assert.equal(synced.pill,'ok');
 assert.equal(c.progressSummary(lab,[job('synced')],NOW),'Saved to Git 12 minutes ago');
 const pushing=c.progressState(lab,[job('pushing')]);
 assert.equal(pushing.label,'Saving progress…');assert.equal(pushing.detail,'Uploading to the online repository…');assert.equal(pushing.pill,'busy');
 assert.equal(c.progressState(lab,[job('capturing')]).detail,'Reading device configurations…');
 assert.equal(c.progressState(lab,[job('exporting',{target:'move'})]).detail,'Moving saved files…');
 const pending=c.progressState(lab,[job('push_pending')]);assert.equal(pending.label,'Needs attention');assert.match(pending.detail,/could not be uploaded to the online repository/);assert.equal(pending.pill,'warn');
 const local=c.progressState(lab,[job('committed')]);assert.equal(local.label,'Saved on this VM');assert.equal(local.pill,'warn');assert.equal(local.key,'local');
 assert.equal(c.progressState(lab,[job('review_pending')]).detail,'Review the changes before uploading.');
 assert.equal(c.progressState(lab,[job('failed')]).label,'Save failed');assert.equal(c.progressState(lab,[job('capture_incomplete')]).pill,'danger');
 assert.equal(c.progressState(lab,[job('interrupted')]).label,'Save interrupted');
 // newest first, ignoring dismissed jobs and repository update markers, and other labs
 const newest=c.progressState(lab,[job('failed',{created:'2026-09-16T10:00:00Z'}),job('synced',{created:'2026-09-16T11:00:00Z'}),job('dismissed',{created:'2026-09-16T11:30:00Z'}),job('push_pending',{created:'2026-09-16T11:40:00Z',target:'update'}),job('failed',{created:'2026-09-16T11:50:00Z',lab_id:'other'})]);
 assert.equal(newest.label,'Saved to Git');
});

test('progress names the upload host, knows unchanged and kept-only saves, and flags a broken save location',()=>{
 const c=makeContext(),job=(status,extra={})=>({id:status,lab_id:'lab',status,target:'latest',created:'2026-09-16T11:48:00Z',finished:'2026-09-16T11:48:30Z',...extra});
 const github={id:'lab',git_binding:{binding_id:'b',repository:{push_url:'https://github.com/course/labs.git'}}};
 assert.equal(c.progressState(github,[job('pushing')]).detail,'Uploading to github.com…');
 assert.match(c.progressState(github,[job('push_pending')]).detail,/could not be uploaded to github\.com\./);
 assert.equal(c.progressState({id:'lab',git_binding:{binding_id:'b',repository:{push_url:'git@gitlab.example.edu:course/labs.git'}}},[job('pushing')]).detail,'Uploading to gitlab.example.edu…');
 assert.equal(c.progressState({id:'lab',git_binding:{binding_id:'b',repository:{push_url:'ssh://git@git.school.local:2222/labs.git'}}},[job('pushing')]).detail,'Uploading to git.school.local…');
 assert.equal(c.progressState({id:'lab',git_binding:{binding_id:'b',repository:{push_url:'nonsense'}}},[job('pushing')]).detail,'Uploading to the online repository…');
 const unchanged=c.progressState(github,[job('unchanged')],NOW);
 assert.equal(unchanged.key,'git');assert.equal(unchanged.label,'Saved to Git');assert.equal(unchanged.detail,'Nothing changed since your last save.');assert.equal(unchanged.pill,'ok');
 const incomplete=c.progressState(github,[job('capture_incomplete')]);
 assert.equal(incomplete.label,'Save failed');assert.equal(incomplete.detail,'A device could not be read, so nothing was saved. Check that every included device is Ready, then try again.');
 const kept=c.progressState(github,[job('dismissed')],NOW);
 assert.equal(kept.label,'Kept on this VM');assert.equal(kept.detail,'Your last save was kept on the VM without uploading.');assert.equal(kept.key,'kept');assert.equal(kept.job.id,'dismissed');
 assert.equal(c.progressSummary(github,[job('dismissed')],NOW),'Kept on this VM 12 minutes ago');
 assert.equal(c.progressState(github,[job('dismissed',{target:'update'})]).label,'Not saved yet','a repository update marker is not a save');
 assert.equal(c.progressState(github,[job('dismissed',{created:'2026-09-16T11:50:00Z'}),job('synced',{created:'2026-09-16T11:00:00Z'})]).label,'Saved to Git','an earlier real save still counts');
 const problem=c.progressState(github,[job('synced')],NOW,'The push URL rejected the VM account.');
 assert.equal(problem.key,'attention');assert.equal(problem.label,'Needs attention');assert.equal(problem.detail,'Saving to Git is not possible right now.');assert.equal(problem.pill,'warn');assert.equal(problem.problem,'The push URL rejected the VM account.');assert.equal(problem.job.id,'synced');
 assert.equal(c.progressState(github,[],NOW,'broken').label,'Needs attention','a broken location matters before the first save too');
 assert.equal(c.progressState(github,[job('pushing')],NOW,'broken').label,'Saving progress…','a save already running still reports its phase');
 assert.equal(c.progressState({id:'lab'},[],NOW,'broken').label,'No save location yet');
 assert.equal(c.progressSummary(github,[job('synced')],NOW,'broken'),'Needs attention');
 const all=['synced','unchanged','committed','review_pending','push_pending','export_pending','capture_incomplete','failed','interrupted','dismissed','pushing'].map(s=>c.progressState(github,[job(s)],NOW));
 for(const p of all)assert.ok(PILLS.includes(p.pill),p.label);
 assert.doesNotMatch(JSON.stringify(all.map(p=>[p.label,p.detail])),/GitHub|router|Not connected/);
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

test('badges, telemetry lines and saved-version names use student words',()=>{
 const c=makeContext();
 assert.equal(c.badgeLabel('reachable'),'Login OK');assert.equal(c.badgeLabel('unreachable'),'Login failed');
 assert.equal(c.badgeLabel('succeeded'),'Succeeded');assert.equal(c.badgeLabel('failed'),'Failed');assert.equal(c.badgeLabel('interrupted'),'Interrupted');
 assert.equal(c.badgeLabel('partial'),'Partly succeeded');assert.equal(c.badgeLabel('queued'),'Queued');assert.equal(c.badgeLabel('running'),'Running');assert.equal(c.badgeLabel('Ready'),'Ready');
 assert.equal(c.badgeLabel('Needs credentials'),'Needs credentials','unknown values pass through');assert.equal(c.badgeLabel(undefined),'');
 assert.equal(c.telemetryLine('streaming',{total:3,streaming:3}),'Collecting live data from 3 devices.');
 assert.equal(c.telemetryLine('streaming',{total:1,streaming:1}),'Collecting live data from 1 device.');
 assert.equal(c.telemetryLine('partial',{total:3,streaming:1,stale:1}),'Some devices are not reporting — open Telemetry settings.');
 assert.equal(c.telemetryLine('waiting',{total:2}),'Waiting for devices to finish starting.');
 assert.equal(c.telemetryLine('failed',{total:3,failed:2}),'2 devices could not be set up for telemetry.');
 assert.equal(c.telemetryLine('failed',{total:3,failed:1}),'1 device could not be set up for telemetry.');
 assert.equal(c.telemetryLine('unsupported',{total:0}),'None of this lab’s devices support telemetry.');
 assert.equal(c.telemetryLine('disabled',{}),'Telemetry is off for this lab.');
 assert.equal(c.telemetryLine('unmonitored',{total:0}),'Available once the lab is running on the VM.');
 assert.equal(c.telemetryLine({status:'streaming',total:2,streaming:2}),'Collecting live data from 2 devices.','the lab.telemetry summary object is accepted directly');
 assert.equal(c.telemetryLine('made-up',{}),'');assert.equal(c.telemetryLine(undefined),'');
 assert.equal(c.savedVersionName('labs/BGP-LAB/reference/solution'),'Final state (instructor)');
 assert.equal(c.savedVersionName('bgp-core/reference/final/'),'Final state (instructor)');
 assert.equal(c.savedVersionName('bgp-core/reference/start'),'Starting state');assert.equal(c.savedVersionName('base'),'Starting state');assert.equal(c.savedVersionName('Initial'),'Starting state');
 assert.equal(c.savedVersionName('bgp-core/reference/broken-01'),'Troubleshooting scenario 01');assert.equal(c.savedVersionName('broken_2'),'Troubleshooting scenario 2');
 assert.equal(c.savedVersionName('bgp-core/work'),'work');assert.equal(c.savedVersionName('ARISTA-LAB-TEST'),'ARISTA-LAB-TEST');assert.equal(c.savedVersionName(''),'');
 assert.doesNotMatch(JSON.stringify(['streaming','partial','waiting','failed','unsupported','disabled','unmonitored'].map(s=>c.telemetryLine(s,{total:2,failed:1,streaming:2}))),/router|node|gNMI|Grafana/i);
});

function pick(o){return {key:o.key,label:o.label,detail:o.detail,pill:o.pill};}
