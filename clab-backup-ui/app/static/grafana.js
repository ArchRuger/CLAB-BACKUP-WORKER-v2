'use strict';
// Opens Grafana for a lab. Grafana is on demand: this page asks the manager to start it on the VM when
// it is stopped (docker start through the reviewed helper), waits until it answers and then moves this
// tab to the dashboard. Only a dashboard path travels in the link; the Grafana origin is the manager's
// own host name on the port the manager announces, so no link can send a viewer elsewhere.
const $=id=>document.getElementById(id);
function grafanaTarget(params,origin,port){
 const raw=params.get('path')||'';
 const path=/^\/d\/[A-Za-z0-9_-]+(\?[A-Za-z0-9_=&%+.-]*)?$/.test(raw)?raw:'/d/clab-lab-overview';
 return `${origin.protocol}//${origin.hostname}:${port}${path}`;
}
async function grafanaRequest(method,url){
 const response=await fetch(url,{method,cache:'no-store',headers:method==='POST'?{'Content-Type':'application/json'}:{},body:method==='POST'?'{}':undefined});
 let data={};try{data=await response.json();}catch{data={};}
 if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'The manager could not reach Grafana.');
 return data;
}
async function launchGrafana(){
 const params=new URLSearchParams(location.hash.slice(1)),title=params.get('title')||'';
 if(title)$('grafana-title').textContent='Grafana · '+title;
 $('grafana-retry').hidden=true;$('grafana-open').hidden=true;
 try{
  const status=await grafanaRequest('GET','/api/telemetry/grafana');
  if(!status.enabled)throw new Error(status.message||'The Grafana stack is not installed on this manager.');
  $('grafana-status').textContent=status.running?'Grafana is running; opening the dashboard…':'Starting Grafana on the VM; this takes a few seconds…';
  const result=status.running?status:await grafanaRequest('POST','/api/telemetry/grafana/start');
  const url=grafanaTarget(params,location,result.port);
  $('grafana-open').href=url;$('grafana-open').hidden=false;
  $('grafana-status').textContent='Grafana is ready.';
  location.replace(url);
 }catch(error){
  $('grafana-status').textContent=error.message;$('grafana-retry').hidden=false;
 }
}
if(typeof document!=='undefined'&&$('grafana-retry')){$('grafana-retry').onclick=launchGrafana;launchGrafana();}
