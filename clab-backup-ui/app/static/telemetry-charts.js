'use strict';
// Pure SVG charts for the Telemetry view: no library, no inline scripts, model data in, markup out.
function telemetryFormatRate(value,unit){
 if(value===null||value===undefined||!Number.isFinite(value))return 'n/a';
 const suffix=unit==='bps'?'b/s':unit==='pps'?'pps':unit||'';
 const trim=s=>s.includes('.')?s.replace(/0+$/,'').replace(/\.$/,''):s;
 const steps=[[1e9,'G'],[1e6,'M'],[1e3,'k']];
 for(const [size,prefix] of steps)if(Math.abs(value)>=size){const v=value/size;return trim(v.toFixed(v>=100?0:v>=10?1:2))+' '+prefix+suffix;}
 const v=Math.abs(value);
 return trim(Number.isInteger(value)?String(value):v<1?value.toFixed(3):v<10?value.toFixed(2):value.toFixed(1))+' '+suffix;
}
function telemetryFormatCount(value){return value===null||value===undefined?'n/a':Number(value).toLocaleString();}
function telemetryAge(ts,now=Date.now()/1000){if(!ts)return 'never';const age=Math.max(0,Math.round(now-ts));return age<60?age+' s ago':age<3600?Math.round(age/60)+' min ago':Math.round(age/3600)+' h ago';}
// A round upper bound: 1, 2, 5 × 10^n above the maximum, never zero.
function telemetryNice(max){if(!Number.isFinite(max)||max<=0)return 1;const power=Math.pow(10,Math.floor(Math.log10(max)));for(const step of [1,2,5,10]){if(max<=step*power)return step*power;}return 10*power;}
function telemetryChart(options){
 const {points=[],series=[],window=300,now=Date.now()/1000,unit='bps',width=640,height=200,title=''}=options;
 const left=64,right=12,top=44,bottom=28,plotW=width-left-right,plotH=height-top-bottom,start=now-window;
 const values=points.flatMap(p=>series.map(s=>p[s.key]).filter(v=>Number.isFinite(v)));
 const max=telemetryNice(Math.max(0,...values)),scale=v=>top+plotH-(v/max)*plotH,x=t=>left+((t-start)/window)*plotW;
 let markup=`<svg class="tele-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(title)}"><text class="tele-chart-title" x="${left}" y="16">${esc(title)}</text>`;
 for(let i=0;i<=4;i++){const v=max*i/4,y=scale(v);markup+=`<line class="tele-grid" x1="${left}" x2="${width-right}" y1="${y}" y2="${y}"/><text class="tele-axis" x="${left-6}" y="${y+4}" text-anchor="end">${esc(telemetryFormatRate(v,unit))}</text>`;}
 const ticks=window<=300?5:window<=900?5:6;
 for(let i=0;i<=ticks;i++){const t=start+window*i/ticks,px=x(t),label=new Date(t*1000).toISOString().slice(11,19);markup+=`<text class="tele-axis" x="${px}" y="${height-8}" text-anchor="${i===0?'start':i===ticks?'end':'middle'}">${label}</text>`;}
 const inWindow=points.filter(p=>p.t>=start&&p.t<=now+1);
 for(const s of series){
  const segments=[];let current=[];
  for(const p of inWindow){const v=p[s.key];if(Number.isFinite(v))current.push(`${x(p.t).toFixed(1)},${scale(v).toFixed(1)}`);else if(current.length){segments.push(current);current=[];}}
  if(current.length)segments.push(current);
  for(const seg of segments)markup+=seg.length>1?`<polyline class="tele-line" data-series="${esc(s.key)}" stroke="${esc(s.color)}" points="${seg.join(' ')}"/>`:`<circle class="tele-point" fill="${esc(s.color)}" cx="${seg[0].split(',')[0]}" cy="${seg[0].split(',')[1]}" r="2.5"/>`;
 }
 if(!inWindow.some(p=>series.some(s=>Number.isFinite(p[s.key]))))markup+=`<text class="tele-empty" x="${left+plotW/2}" y="${top+plotH/2}" text-anchor="middle">No samples in this window yet</text>`;
 // The legend sits on its own line under the title, clear of the time axis.
 markup+='<g class="tele-legend">'+series.map((s,i)=>{const last=[...inWindow].reverse().find(p=>Number.isFinite(p[s.key]));return `<rect x="${left+i*150}" y="${top-18}" width="10" height="10" fill="${esc(s.color)}"/><text x="${left+i*150+14}" y="${top-9}">${esc(s.label)} · ${esc(telemetryFormatRate(last?last[s.key]:null,unit))}</text>`;}).join('')+'</g></svg>';
 return markup;
}
