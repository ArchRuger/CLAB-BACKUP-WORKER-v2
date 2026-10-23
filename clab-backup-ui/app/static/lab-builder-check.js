'use strict';
// The lab builder's topology check (docs/parity-campaign/C08-DESIGN.md §2.2 and §3). Pure functions of plain
// data: the located tree the adapter's locateYaml(text) gives (§2.1), the containerlab schema the panel fetched
// (app/static/clab-schema/<version>.json, verbatim upstream data, never executed) and the context of §2.2. No DOM,
// no fetch, no timer: the file loads in a bare Node context for its tests and beside the other builder scripts.
// Every finding is advisory (decision 4): nothing here refuses Apply or Save. The severity of each rule follows
// the evidence table of §3; a rule the session could not prove is a warning whose sentence says what happens.
// Student text is only ever the subject of RegExp.test: every pattern comes from the vendored schema.
// The vendored schemas (app/static/clab-schema/<version>.json); test_clab_schema.py pins this list to the files.
const BUILDER_SCHEMA_VERSIONS=['0.79.0'];
const BUILDER_CHECK_LIMIT=200;
// The longest scalar a schema pattern is tested on; a longer one is reported as too long to check.
const BUILDER_CHECK_TEXT_LIMIT=1024;
// The walker's own depth guard (locateYaml caps the tree at 64 levels already).
const BUILDER_CHECK_DEPTH=64;
const BUILDER_CHECK_STAGES=['create','create-links','configure','healthy','exit'];
const BUILDER_CHECK_LINK_TYPES=['veth','veth-stitch','mgmt-net','host','macvlan','vxlan','vxlan-stitch','dummy'];
// Endpoint names that are containerlab's special endpoints, not devices (the list main.tsx yamlFlaw uses, plus bridge).
const BUILDER_CHECK_LINK_SPECIAL=['host','mgmt-net','macvlan','vxlan','vxlan-stitch','dummy','bridge'];
// The enums §3 R4 names: an error when the schema matches the VM exactly, otherwise a warning; every other enum is a warning.
const BUILDER_CHECK_ENUM_KEYS=['restart-policy','image-pull-policy','runtime'];
// Keys containerlab accepts although its schema omits them, per schema version (§3).
const BUILDER_SCHEMA_EXTRA_KEYS={
 // containerlab v0.79.0 types/node_definition.go: NodeDefinition.Position (accepted silently on a node, in defaults,
 // kinds and groups); NodeDefinitionWithDeprecatedFields.LegacyUsername / LegacyPassword (still read; the current form
 // is credentials).
 '0.79.0':{position:'silent',username:'login',password:'login'}
};
// Renamed in containerlab 0.41 and still read by the …WithDeprecatedFields decoders §0's error texts name (§3).
const BUILDER_DEPRECATED_KEYS={mgmt_ipv4:'mgmt-ipv4',mgmt_ipv6:'mgmt-ipv6',ipv4_subnet:'ipv4-subnet',ipv6_subnet:'ipv6-subnet'};
// The closed maps where `containerlab validate` proved an unknown key is refused (§0, sixteen probes): the root,
// mgmt, a node under nodes, stages and a wait-for entry. A level joins only when a §7.4 probe of it is recorded here.
const BUILDER_PROBED_LEVELS={'0.79.0':['root','mgmt','node','stages','wait-for']};
// Kind names containerlab 0.79.0 accepts although the schema's kind enum does not list them (§0: the list
// `kind "nosuchkind" is not supported. Supported kinds are …` prints): every vr-* name and these short names.
const BUILDER_KIND_ALIASES={prefix:'vr-',short:['ceos','srl','xrd','cvx','cumulus_cvx','crpd','cjunosevolved','c8000']};
// The current name of an alias where the manager's own catalog names one (mirrored from inventory.ALIASES in app/inventory.py).
const BUILDER_KIND_LONG={ceos:'arista_ceos',cjunosevolved:'juniper_cjunosevolved','vr-vqfx':'juniper_vqfx','vr-vjunosswitch':'juniper_vjunosswitch','vr-vjunosrouter':'juniper_vjunosrouter','vr-xrv9k':'cisco_xrv9k'};
const BUILDER_NO_IMAGE_KINDS=['bridge','ovs-bridge','host','ext-container'];
// Kinds whose containers define no health check on the development VM (§0, `docker ps`): a wait for healthy never ends.
const BUILDER_NO_HEALTHCHECK_KINDS=['arista_ceos','ceos','juniper_cjunosevolved','cjunosevolved','linux'];
// The manager's own name rule for devices (discovery.identifier): the review refuses anything else.
const BUILDER_CHECK_MANAGER_NAME=/^[A-Za-z0-9_][A-Za-z0-9_.-]*$/;
// Compiled schema patterns, by source text: {re, risky} or null when the pattern does not compile here.
const BUILDER_CHECK_REGEX=new Map();

// --- small pieces ---------------------------------------------------------------------------------------
function builderCheckIsMap(n){return !!n&&n.kind==='map'&&Array.isArray(n.items);}
function builderCheckIsSeq(n){return !!n&&n.kind==='seq'&&Array.isArray(n.items);}
function builderCheckIsScalar(n){return !!n&&n.kind==='scalar';}
function builderCheckIsNull(n){return !n||(n.kind==='scalar'&&(n.value===null||n.value===undefined));}
function builderCheckGet(map,key){if(!builderCheckIsMap(map))return undefined;for(const item of map.items)if(item&&item.key===key)return item;return undefined;}
function builderCheckValue(map,key){const e=builderCheckGet(map,key);return e?e.value:undefined;}
// The scalar's YAML type: the adapter's tag when it gives one, else the JavaScript type of the value.
function builderCheckTag(n){
 if(!builderCheckIsScalar(n))return '';
 if(n.tag==='str'||n.tag==='int'||n.tag==='float'||n.tag==='bool'||n.tag==='null')return n.tag;
 const v=n.value;if(v===null||v===undefined)return 'null';if(typeof v==='boolean')return 'bool';if(typeof v==='number')return Number.isInteger(v)?'int':'float';return 'str';
}
function builderCheckJsonType(n){
 if(builderCheckIsMap(n))return 'object';if(builderCheckIsSeq(n))return 'array';
 return {str:'string',int:'integer',float:'number',bool:'boolean',null:'null'}[builderCheckTag(n)]||'null';
}
function builderCheckTypeMatches(n,type){
 const t=builderCheckJsonType(n),list=Array.isArray(type)?type:[type];
 return list.some(x=>x===t||(x==='number'&&t==='integer'));
}
// A scalar as text (Go's decoder puts a plain scalar into a string field), or '' for anything else.
function builderCheckText(n){if(!builderCheckIsScalar(n)||builderCheckIsNull(n))return '';return String(n.value);}
function builderCheckShow(s){s=String(s??'');return s.length>60?s.slice(0,59)+'…':s;}
function builderCheckNoun(type){return {object:'a mapping',array:'a list',string:'text',integer:'a whole number',number:'a number',boolean:'true or false',null:'empty'}[type]||'a value';}
function builderCheckList(values,last){values=values.map(v=>String(v));return values.length<2?values.join(''):values.slice(0,-1).join(', ')+' '+(last||'and')+' '+values[values.length-1];}
function builderCheckIsIndex(step){return /^\d+$/.test(String(step));}
// The key a finding talks about: `env`, or "item 2 of `binds`" inside a list.
function builderCheckLabel(path){
 const last=path[path.length-1];
 if(builderCheckIsIndex(last)){const parent=path.length>1?path[path.length-2]:'';return 'item '+(Number(last)+1)+' of `'+builderCheckShow(parent)+'`';}
 return '`'+builderCheckShow(last)+'`';
}
// The nearest key name on the path (the list's key for an item).
function builderCheckKey(path){for(let i=path.length-1;i>=0;i--)if(!builderCheckIsIndex(path[i]))return String(path[i]);return '';}
function builderCheckCap(s){s=String(s);return s.charAt(0).toUpperCase()+s.slice(1);}
// Plain data for uniqueItems (depth-capped, so a crafted tree cannot exhaust the stack).
function builderCheckPlain(n,depth){
 depth=depth||0;if(depth>BUILDER_CHECK_DEPTH)return '…';
 if(builderCheckIsMap(n))return Object.fromEntries(n.items.map(i=>[i.key,builderCheckPlain(i.value,depth+1)]));
 if(builderCheckIsSeq(n))return n.items.map(i=>builderCheckPlain(i,depth+1));
 return builderCheckIsScalar(n)?(n.value??null):null;
}
// Optimal string alignment distance, bounded: longer words are not compared.
function builderCheckDistance(a,b){
 if(a.length>64||b.length>64)return 99;
 const d=[];for(let i=0;i<=a.length;i++){d.push([i]);}for(let j=1;j<=b.length;j++)d[0][j]=j;
 for(let i=1;i<=a.length;i++)for(let j=1;j<=b.length;j++){
  const cost=a[i-1]===b[j-1]?0:1;d[i][j]=Math.min(d[i-1][j]+1,d[i][j-1]+1,d[i-1][j-1]+cost);
  if(i>1&&j>1&&a[i-1]===b[j-2]&&a[i-2]===b[j-1])d[i][j]=Math.min(d[i][j],d[i-2][j-2]+1);
 }
 return d[a.length][b.length];
}
// The listed word a typo most likely meant: the same word but for -, _ and case, else the closest within two edits.
function builderCheckSuggest(word,candidates){
 word=String(word);const norm=s=>String(s).toLowerCase().replace(/[-_]/g,'');
 const list=candidates.map(String).filter(c=>c!==word);
 const same=list.find(c=>norm(c)===norm(word));if(same)return same;
 let best='',score=3;
 for(const c of list){const d=builderCheckDistance(word.toLowerCase(),c.toLowerCase());if(d<score&&d<word.length){best=c;score=d;}}
 return best;
}
function builderCheckMean(word,candidates){const s=builderCheckSuggest(word,candidates);return s?' Did you mean `'+s+'`?':'';}

// --- the schema's patterns ------------------------------------------------------------------------------
// A group repeated without bound whose body repeats or alternates (`(a+)+`, `([0-9]{1,4}|…)+`): the shape that
// backtracks exponentially on a crafted string. Such a pattern is tested only behind a guard of its own rule.
function builderCheckRisky(src){
 const stack=[];let inClass=false;
 const quant=c=>c==='+'||c==='*'||c==='?'||c==='{';
 for(let i=0;i<src.length;i++){
  const c=src[i];
  if(c==='\\'){i++;continue;}
  if(inClass){if(c===']')inClass=false;continue;}
  if(c==='['){inClass=true;continue;}
  if(c==='('){stack.push({inner:false});if(src[i+1]==='?')i+=2;continue;}
  if(c===')'){
   const group=stack.pop()||{inner:false},next=src[i+1];
   const unbounded=next==='+'||next==='*'||(next==='{'&&/^\{\d+,\}/.test(src.slice(i+1)));
   if(unbounded&&group.inner)return true;
   if(stack.length&&(group.inner||quant(next)))stack[stack.length-1].inner=true;
   continue;
  }
  if((c==='|'||quant(c))&&stack.length)stack[stack.length-1].inner=true;
 }
 return false;
}
// The `u` flag only where the pattern needs it (\p{…}); a pattern that does not compile disables that one check.
function builderCheckRegex(src){
 if(BUILDER_CHECK_REGEX.has(src))return BUILDER_CHECK_REGEX.get(src);
 let entry=null;try{entry={re:new RegExp(src,src.includes('\\p{')?'u':''),risky:builderCheckRisky(src)};}catch{entry=null;}
 BUILDER_CHECK_REGEX.set(src,entry);return entry;
}
// true or false, 'long' for a text over the limit, null when the pattern is not tested (does not compile, or
// backtracks without a guard).
function builderCheckMatch(src,text,guarded){
 if(text.length>BUILDER_CHECK_TEXT_LIMIT)return 'long';
 const entry=builderCheckRegex(src);if(!entry||(entry.risky&&!guarded))return null;
 return entry.re.test(text);
}
// The port rule's guard: no port number or address octet has six digits (the zone after % aside), and with no
// longer digit run the schema's repeated port group cannot backtrack far.
function builderCheckPortGuard(text){return !/[0-9]{6,}/.test(text.replace(/%[^:]*/,''));}
// Every pattern of a schema compiled once: the tests require zero failures for each vendored file.
function builderCheckSelfTest(schema){
 const result={patterns:0,failed:0,failures:[],risky:[]},seen=new Set();
 const stack=[[schema,'#']];
 while(stack.length){
  const [node,where]=stack.pop();if(!node||typeof node!=='object')continue;
  if(seen.has(node))continue;seen.add(node);
  const sources=[];if(typeof node.pattern==='string')sources.push([node.pattern,where+'/pattern']);
  if(node.patternProperties&&typeof node.patternProperties==='object')for(const key of Object.keys(node.patternProperties))sources.push([key,where+'/patternProperties']);
  for(const [src,at] of sources){result.patterns++;const entry=builderCheckRegex(src);if(!entry){result.failed++;result.failures.push(at);}else if(entry.risky)result.risky.push(at);}
  for(const [key,value] of Object.entries(node))if(value&&typeof value==='object')stack.push([value,where+'/'+key]);
 }
 return result;
}

// --- the run: findings, severities, the schema --------------------------------------------------------
function builderCheckStart(schema,context){
 const ctx=context&&typeof context==='object'?context:{};
 const version=typeof ctx.schemaVersion==='string'?ctx.schemaVersion:'';
 return {schema:schema&&typeof schema==='object'?schema:null,exact:ctx.exact===true,version,
  out:[],aliases:new Set(),probed:BUILDER_PROBED_LEVELS[version]||[],extras:BUILDER_SCHEMA_EXTRA_KEYS[version]||{}};
}
function builderCheckSub(r){return Object.assign({},r,{out:[]});}
function builderCheckAdd(r,severity,line,code,path,message){r.out.push({severity,line:Number(line)>0?Number(line):1,message,code,path:path.map(String)});}
function builderCheckExact(r){return r.exact?'error':'warning';}
function builderCheckClab(r){return r.version?'containerlab '+r.version:'containerlab';}
// A local `#/definitions/…` reference, merged under the keys beside it; any other reference is dropped, never fetched.
function builderCheckResolve(r,sch){
 let hops=0;
 while(sch&&typeof sch==='object'&&typeof sch.$ref==='string'&&hops++<16){
  const rest=Object.assign({},sch);delete rest.$ref;
  const m=/^#\/definitions\/([^/]+)$/.exec(sch.$ref);
  const target=m&&r.schema&&r.schema.definitions&&Object.prototype.hasOwnProperty.call(r.schema.definitions,m[1])?r.schema.definitions[m[1]]:null;
  sch=target&&typeof target==='object'?Object.assign({},target,rest):rest;
 }
 return sch&&typeof sch==='object'?sch:null;
}
function builderCheckDef(r,name){return r.schema&&r.schema.definitions?builderCheckResolve(r,r.schema.definitions[name]):null;}
function builderCheckPatternProp(sch,key){
 if(!sch||!sch.patternProperties||typeof sch.patternProperties!=='object')return undefined;
 for(const [src,sub] of Object.entries(sch.patternProperties)){const entry=builderCheckRegex(src);if(entry&&!entry.risky&&String(key).length<=BUILDER_CHECK_TEXT_LIMIT&&entry.re.test(String(key)))return sub;}
 return undefined;
}

// --- R1: an unknown key -----------------------------------------------------------------------------------
// The level of a map for R1, from its path: root, mgmt, topology, node, defaults, kinds, groups, kinds-map,
// stages, stage, wait-for, exec, link, endpoint, or the key that holds it.
function builderCheckLevel(path){
 const p=path.map(String),n=p.length,last=p[n-1];
 if(!n)return 'root';
 if(n===1)return last==='mgmt'?'mgmt':last==='topology'?'topology':last;
 if(p[0]==='topology'){
  if(n===3&&p[1]==='nodes')return 'node';
  if(n===2&&p[1]==='defaults')return 'defaults';
  if(n===2&&p[1]==='kinds')return 'kinds-map';
  if(n===3&&p[1]==='kinds')return 'kinds';
  if(n===3&&p[1]==='groups')return 'groups';
  if(n===3&&p[1]==='links')return 'link';
 }
 if(last==='stages')return 'stages';
 if(n>=2&&p[n-2]==='stages')return 'stage';
 if(builderCheckIsIndex(last)&&p[n-2]==='wait-for')return 'wait-for';
 if(builderCheckIsIndex(last)&&p[n-2]==='exec'&&n>=4&&p[n-4]==='stages')return 'exec';
 if(p[0]==='topology'&&p[1]==='links'&&(last==='endpoint'||(builderCheckIsIndex(last)&&p[n-2]==='endpoints')))return 'endpoint';
 return builderCheckKey(p);
}
function builderCheckUnknown(r,entry,path,known,where){
 const level=builderCheckLevel(path),key=String(entry.key),k='`'+builderCheckShow(key)+'`',clab=builderCheckClab(r);
 const severity=r.exact&&r.probed.includes(level)?'error':'warning',mean=builderCheckMean(key,known);
 let message;
 if(level==='root')message=k+' is not a top-level section ('+known.join(', ')+').'+mean;
 else if(level==='topology')message=k+' is not a section of topology ('+known.join(', ')+').'+mean;
 else if(level==='node')message=k+' is not a device setting '+clab+' knows.'+mean;
 else if(level==='defaults'||level==='kinds'||level==='groups')message=k+' is not a device setting '+clab+' knows (in '+path.join('.')+').'+mean;
 else if(level==='kinds-map')message=k+' is not a kind '+clab+' takes settings for in topology.kinds.'+mean;
 else if(level==='mgmt')message=k+' is not a mgmt setting '+clab+' knows.'+mean;
 else if(level==='stage')message=k+' is not a setting of a stage; a stage takes wait-for and exec.'+mean;
 else if(level==='wait-for'){builderCheckAdd(r,severity,entry.keyLine,'wait-extra',path.concat(key),'a wait-for entry has `node` and `stage` only; '+k+' is not a setting.');return;}
 else if(level==='exec')message=k+' is not a setting of a stage command (command, phase, target).'+mean;
 else if(level==='link')message=k+' is not a setting of '+(where||'a link')+'.'+mean;
 else if(level==='endpoint')message=k+' is not a setting of a link endpoint ('+known.join(', ')+').'+mean;
 else message=k+' is not a setting '+clab+' knows in '+path.join('.')+'.'+mean;
 builderCheckAdd(r,severity,entry.keyLine,'unknown-key',path.concat(key),message);
}

// --- the walker: the schema's keywords over the tree ----------------------------------------------------
// R5: the wrong YAML type for a key. An error for a collection against a scalar (either way) and for text where a
// number is expected (Go's decoder refuses both); a scalar against another scalar is a warning.
function builderCheckWrongType(r,loc,sch,path,line){
 const want=Array.isArray(sch.type)?sch.type[0]:sch.type,got=builderCheckJsonType(loc),label=builderCheckLabel(path),key=builderCheckKey(path);
 const collection=t=>t==='object'||t==='array';
 if(collection(want)||collection(got)){
  const message=key==='env'&&!builderCheckIsIndex(path[path.length-1])?'`env` must be a mapping of NAME: value, not '+builderCheckNoun(got)+'.':label+' must be '+builderCheckNoun(want)+', not '+builderCheckNoun(got)+'.';
  builderCheckAdd(r,'error',line,'type',path,message);return;
 }
 const text=builderCheckShow(loc.value);
 if((want==='number'||want==='integer')&&got==='string'){
  const numeric=String(loc.value).trim()!==''&&Number.isFinite(Number(loc.value));
  builderCheckAdd(r,'error',line,'type',path,label+' must be '+builderCheckNoun(want)+', not the text `'+text+'`'+(numeric?'; write it without quotes.':'.'));return;
 }
 if(want==='string'&&(got==='integer'||got==='number'||got==='boolean')){builderCheckAdd(r,'warning',line,'type',path,label+' is read as the text `'+text+'`; quote it if that is meant.');return;}
 builderCheckAdd(r,'warning',line,'type',path,label+' must be '+builderCheckNoun(want)+', not `'+text+'`.');
}
// R6a and R6b: what a failed pattern means, by key.
function builderCheckPatternMessage(path,value){
 const v='`'+builderCheckShow(value)+'`',key=builderCheckKey(path);
 const said={
  'network-mode':v+' is not a network mode containerlab documents (host, none, container:<name>); Docker refuses it when the lab is deployed.',
  'mgmt-ipv4':v+' is not an IPv4 address.','ipv4-gw':v+' is not an IPv4 address.','mgmt-ipv6':v+' is not an IPv6 address.','ipv6-gw':v+' is not an IPv6 address.',
  remote:v+' is not an IP address.','ipv4-subnet':v+' is not an IPv4 subnet (for example 172.20.20.0/24) or auto.','ipv6-subnet':v+' is not an IPv6 subnet (for example 3fff:172:20:20::/64) or auto.',
  'ipv4-range':v+' is not an address range with a prefix length (for example 172.20.20.128/25).','ipv6-range':v+' is not an address range with a prefix length (for example 3fff:172:20:20::/80).',
  'shm-size':v+' is not a size (for example 512mb or 1gb).',mac:v+' is not a MAC address (for example 02:00:00:00:00:01).',
  ipv4:v+' is not an IPv4 address with a prefix length (for example 192.168.0.1/24).',ipv6:v+' is not an IPv6 address with a prefix length (for example 2001:db8::1/64).',
  slot:v+' is not a slot (A, B or a number).'
 };
 return said[key]||v+' does not have the form containerlab expects for `'+builderCheckShow(key)+'`.';
}
// R6a for the lab name and the prefix: the manager refuses them too (M), so an error on any VM.
function builderCheckHardName(r,loc,sch,path,line){
 const key=String(path[0]),text=String(loc.value),shown='`'+builderCheckShow(text)+'`';
 if(key==='prefix'&&(text===''||text==='__lab-name'))return;
 const result=builderCheckMatch(sch.pattern,text,false);
 if(result==='long'){builderCheckAdd(r,'warning',line,'too-long',path,'`'+key+'` is too long to check (more than 1,024 characters).');return;}
 if(result!==false&&BUILDER_CHECK_MANAGER_NAME.test(text))return;
 const what=key==='name'?'the lab name '+shown:'the prefix '+shown;
 const message=/^[A-Za-z0-9]/.test(text)?what+' can only use letters, digits, dot, dash and underscore'+(key==='prefix'?' (or be empty, or __lab-name).':'.'):what+' must start with a letter or digit.';
 builderCheckAdd(r,'error',line,'pattern-hard',path,message);
}
// The node-level keys a rule owns: the walker reports nothing there (§3 "Rule-owned paths").
function builderCheckWalk(r,loc,sch,path,line,o){
 o=o||{};
 if(!loc||!sch)return;
 if(path.length>BUILDER_CHECK_DEPTH){builderCheckAdd(r,'warning',line,'too-deep',path.slice(0,BUILDER_CHECK_DEPTH),'This part of the topology nests too deep to check.');return;}
 sch=builderCheckResolve(r,sch);if(!sch)return;
 if(builderCheckIsNull(loc))return;
 const key=builderCheckKey(path),last=path[path.length-1];
 // R6c: a bind is host-path:container-path[:ro]. A number is refused (P: `Bind "1" looks like an anonymous volume target`).
 if(builderCheckIsIndex(last)&&path[path.length-2]==='binds'&&builderCheckIsScalar(loc)){
  const text=String(loc.value),tag=builderCheckTag(loc);
  if(tag!=='str')builderCheckAdd(r,'error',line,'binds',path,'a bind is `host-path:container-path[:ro]`; `'+builderCheckShow(text)+'` is not one.');
  else if(!text.includes(':'))builderCheckAdd(r,'warning',line,'binds',path,'a bind is `host-path:container-path[:ro]`; `'+builderCheckShow(text)+'` is not one.');
  return;
 }
 if(sch.type!==undefined&&!builderCheckTypeMatches(loc,sch.type)){builderCheckWrongType(r,loc,sch,path,line);return;}
 for(const word of ['anyOf','oneOf'])if(Array.isArray(sch[word])&&!builderCheckBranches(r,loc,sch[word],path,line,o))return;
 if(builderCheckIsScalar(loc))builderCheckScalar(r,loc,sch,path,line,o);
 else if(builderCheckIsSeq(loc))builderCheckSeq(r,loc,sch,path,line);
 else if(builderCheckIsMap(loc))builderCheckMap(r,loc,sch,path,line,o);
 if(Array.isArray(sch.allOf))for(const part of sch.allOf){
  const p=builderCheckResolve(r,part);if(!p)continue;
  if(p.if){const target=builderCheckIf(r,loc,p.if,o)?p.then:p.else;if(target)builderCheckWalk(r,loc,target,path,line,{kind:o.kind,skip:o.skip,partial:true});}
  else builderCheckWalk(r,loc,p,path,line,{kind:o.kind,skip:o.skip,partial:true});
 }
}
// anyOf/oneOf: the first branch whose type matches (a non-null one when none does) is tried first; the value passes
// when any branch has nothing to say, otherwise the first branch's findings are reported, so the sentence names
// that form's problem instead of "matches no form". Branches with nothing to test (only required/not) are skipped.
function builderCheckBranches(r,loc,list,path,line,o){
 const branches=list.map(b=>builderCheckResolve(r,b)).filter(Boolean);
 const useful=branches.some(b=>['type','enum','const','pattern','properties','items'].some(k=>b[k]!==undefined));
 if(!useful)return true;
 const typed=branches.find(b=>b.type!==undefined&&builderCheckTypeMatches(loc,b.type))||branches.find(b=>b.type!==undefined&&b.type!=='null')||branches[0];
 const order=[typed,...branches.filter(b=>b!==typed)];let first=null;
 for(const b of order){const scratch=builderCheckSub(r);builderCheckWalk(scratch,loc,b,path,line,o);if(!scratch.out.length)return true;if(!first)first=scratch.out;}
 r.out.push(...first);return false;
}
// `if` as the schema uses it: properties tested on the keys present (the device's resolved kind stands in for kind),
// required keys present.
function builderCheckIf(r,loc,cond,o){
 cond=builderCheckResolve(r,cond);if(!cond||!builderCheckIsMap(loc))return false;
 const value=key=>key==='kind'&&o&&typeof o.kind==='string'&&o.kind?{kind:'scalar',line:0,value:o.kind,tag:'str'}:builderCheckValue(loc,key);
 for(const key of Array.isArray(cond.required)?cond.required:[])if(builderCheckIsNull(value(key)))return false;
 for(const [key,sub] of Object.entries(cond.properties||{})){
  const v=value(key);if(builderCheckIsNull(v))continue;
  const s=builderCheckResolve(r,sub);if(!s)continue;
  if(s.type!==undefined&&!builderCheckTypeMatches(v,s.type))return false;
  if(typeof s.pattern==='string'){if(!builderCheckIsScalar(v))return false;const m=builderCheckMatch(s.pattern,String(v.value),false);if(m!==true)return false;}
 }
 return true;
}
function builderCheckScalar(r,loc,sch,path,line,o){
 const key=builderCheckKey(path),text=String(loc.value),shown='`'+builderCheckShow(text)+'`',label=builderCheckLabel(path);
 if(Array.isArray(sch.enum)&&!sch.enum.some(e=>e===loc.value||String(e)===text)){
  const values=[];for(const e of sch.enum){const low=String(e).toLowerCase();if(!values.includes(low))values.push(low);}
  if(key==='type'&&o.kind)builderCheckAdd(r,'warning',line,'enum',path,shown+' is not a type '+builderCheckClab(r)+' knows for the kind `'+builderCheckShow(o.kind)+'`.'+builderCheckMean(text,sch.enum));
  else{
   const severity=BUILDER_CHECK_ENUM_KEYS.includes(key)&&!builderCheckIsIndex(path[path.length-1])?builderCheckExact(r):'warning';
   builderCheckAdd(r,severity,line,'enum',path,shown+' is not a value '+builderCheckClab(r)+' accepts for '+label+'.'+(values.length<=12?' The values are '+builderCheckList(values)+'.':'')+builderCheckMean(text,values));
  }
  return;
 }
 if(sch.const!==undefined&&String(sch.const)!==text){builderCheckAdd(r,'warning',line,'const',path,label+' must be `'+builderCheckShow(sch.const)+'`.');return;}
 if(typeof sch.pattern==='string'&&builderCheckTag(loc)==='str'){
  if(path.length===1&&(key==='name'||key==='prefix')){builderCheckHardName(r,loc,sch,path,line);return;}
  // R6a: a port mapping containerlab refuses (P: `Invalid containerPort: abc`).
  const port=key==='ports'&&builderCheckIsIndex(path[path.length-1]);
  const result=port&&!builderCheckPortGuard(text)?false:builderCheckMatch(sch.pattern,text,port);
  if(result==='long'){builderCheckAdd(r,'warning',line,'too-long',path,label+' is too long to check (more than 1,024 characters).');return;}
  if(result===false){
   if(port)builderCheckAdd(r,'error',line,'pattern-hard',path,shown+' is not a port mapping (host:container, e.g. 8080:80).');
   else builderCheckAdd(r,'warning',line,'pattern-soft',path,builderCheckPatternMessage(path,text));
   return;
  }
 }
 if(typeof sch.minLength==='number'&&builderCheckTag(loc)==='str'&&text.length<sch.minLength)builderCheckAdd(r,'warning',line,'limit',path,sch.minLength===1?label+' must not be empty.':label+' must be at least '+sch.minLength+' characters long.');
 const tag=builderCheckTag(loc);
 if((tag==='int'||tag==='float')&&typeof loc.value==='number'){
  if(typeof sch.minimum==='number'&&loc.value<sch.minimum)builderCheckAdd(r,'warning',line,'limit',path,label+' must be at least '+sch.minimum+'.');
  if(typeof sch.maximum==='number'&&loc.value>sch.maximum)builderCheckAdd(r,'warning',line,'limit',path,label+' must be at most '+sch.maximum+'.');
 }
}
function builderCheckSeq(r,loc,sch,path,line){
 const label=builderCheckLabel(path),n=loc.items.length;
 if(typeof sch.minItems==='number'&&n<sch.minItems)builderCheckAdd(r,'warning',line,'limit',path,label+' needs at least '+sch.minItems+' item'+(sch.minItems===1?'':'s')+'.');
 if(typeof sch.maxItems==='number'&&n>sch.maxItems)builderCheckAdd(r,'warning',line,'limit',path,label+' takes at most '+sch.maxItems+' item'+(sch.maxItems===1?'':'s')+'.');
 if(sch.uniqueItems===true){const seen=new Set();loc.items.forEach((item,i)=>{const id=JSON.stringify(builderCheckPlain(item));if(seen.has(id))builderCheckAdd(r,'warning',item.line||line,'unique',path.concat(String(i)),label+' lists the same entry twice.');seen.add(id);});}
 loc.items.forEach((item,i)=>{
  const sub=Array.isArray(sch.prefixItems)&&i<sch.prefixItems.length?sch.prefixItems[i]:sch.items;
  if(sub&&typeof sub==='object'&&!Array.isArray(sub))builderCheckWalk(r,item,sub,path.concat(String(i)),item.line||line);
 });
}
// A mapping: deprecated names first (a warning, the value checked under the current name), then the version's extra
// keys, then the schema's properties and patternProperties; with additionalProperties false anything else is R1.
// o.skip names the rule-owned keys (kind, stages); o.partial marks an allOf part (no R1, no required there).
function builderCheckMap(r,loc,sch,path,line,o){
 const props=sch.properties&&typeof sch.properties==='object'?sch.properties:{},known=Object.keys(props),skip=o.skip||[];
 const nodeConfig=!!o.nodeConfig;
 for(const entry of loc.items){
  if(!entry)continue;
  const key=String(entry.key),here=path.concat(key);
  if(skip.includes(key))continue;
  if(Object.prototype.hasOwnProperty.call(props,key)){builderCheckWalk(r,entry.value,props[key],here,entry.keyLine,{kind:o.kind});continue;}
  if(o.partial)continue;
  const renamed=Object.prototype.hasOwnProperty.call(BUILDER_DEPRECATED_KEYS,key)?BUILDER_DEPRECATED_KEYS[key]:'';
  if(renamed&&Object.prototype.hasOwnProperty.call(props,renamed)){
   builderCheckAdd(r,'warning',entry.keyLine,'renamed-key',here,'`'+key+'` is an old name containerlab still accepts; the current name is `'+renamed+'`.');
   builderCheckWalk(r,entry.value,props[renamed],path.concat(renamed),entry.keyLine,{kind:o.kind});continue;
  }
  if(nodeConfig&&Object.prototype.hasOwnProperty.call(r.extras,key)){
   if(r.extras[key]==='login')builderCheckAdd(r,'warning',entry.keyLine,'legacy-login',here,'`'+key+'` is an old place for the login; containerlab still reads it, the current form is `credentials: {username: …, password: …}`.');
   continue;
  }
  const pattern=builderCheckPatternProp(sch,key);
  if(pattern!==undefined){builderCheckWalk(r,entry.value,pattern,here,entry.keyLine,{kind:o.kind});continue;}
  if(sch.additionalProperties===false)builderCheckUnknown(r,entry,path,known,o.where);
  else if(sch.additionalProperties&&typeof sch.additionalProperties==='object')builderCheckWalk(r,entry.value,sch.additionalProperties,here,entry.keyLine,{kind:o.kind});
 }
 if(o.partial)return;
 for(const key of Array.isArray(sch.required)?sch.required:[]){
  if(builderCheckGet(loc,key)||(o.optional||[]).includes(key))continue;
  if(!path.length)builderCheckAdd(r,'warning',line,'required',path.concat(key),'The file has no `'+key+':`; containerlab needs it.');
  else builderCheckAdd(r,'warning',line,'required',path.concat(key),builderCheckLabel(path)+' has no `'+key+':`, which containerlab needs.');
 }
 if(typeof sch.minProperties==='number'&&loc.items.length<sch.minProperties)builderCheckAdd(r,'warning',line,'limit',path,builderCheckLabel(path)+' is empty; give it a setting or remove it.');
}

// --- the topology: devices, inheritance, kinds, images ----------------------------------------------------
function builderCheckAlias(kind){return kind.startsWith(BUILDER_KIND_ALIASES.prefix)||BUILDER_KIND_ALIASES.short.includes(kind);}
function builderCheckKindEnum(r){const s=builderCheckDef(r,'node-config');const k=s&&s.properties?builderCheckResolve(r,s.properties.kind):null;return k&&Array.isArray(k.enum)?k.enum.map(String):[];}
// A device's own settings, its group's, its kind section's and the defaults: the order containerlab resolves a
// setting in (discovery.parse_definition).
function builderCheckChain(t,nodeMap,kind){
 const groups=builderCheckValue(t,'groups'),kinds=builderCheckValue(t,'kinds'),defaults=builderCheckValue(t,'defaults');
 const groupName=builderCheckText(builderCheckValue(nodeMap,'group'));
 const chain=[{map:builderCheckIsMap(nodeMap)?nodeMap:null,where:''}];
 if(groupName&&builderCheckIsMap(builderCheckValue(groups,groupName)))chain.push({map:builderCheckValue(groups,groupName),where:'topology.groups.'+groupName});
 if(kind){const own=builderCheckValue(kinds,kind)||builderCheckValue(kinds,BUILDER_KIND_LONG[kind]||'');if(builderCheckIsMap(own))chain.push({map:own,where:'topology.kinds.'+(builderCheckIsMap(builderCheckValue(kinds,kind))?kind:BUILDER_KIND_LONG[kind])});}
 if(builderCheckIsMap(defaults))chain.push({map:defaults,where:'topology.defaults'});
 return chain;
}
// The entry that gives a device its kind: the device, its group, then the defaults (a kind section cannot).
function builderCheckKindEntry(t,nodeMap){
 for(const link of builderCheckChain(t,nodeMap,'')){const e=builderCheckGet(link.map,'kind');if(e&&!builderCheckIsNull(e.value))return e;}
 return undefined;
}
// A setting is given when it has a value: empty text is none, a wrongly typed value is reported by R5, not as missing.
function builderCheckSetting(chain,key){for(const link of chain){const e=builderCheckGet(link.map,key);if(e&&!builderCheckIsNull(e.value)&&!(builderCheckIsScalar(e.value)&&String(e.value.value)===''))return e;}return undefined;}
function builderCheckHas(chain,key){for(const link of chain){const e=builderCheckGet(link.map,key);if(e&&!builderCheckIsNull(e.value))return true;}return false;}
// One node-config mapping (a device, the defaults, a kinds entry or a group): the walker without the rule-owned
// keys, then the stage structure.
function builderCheckNodeConfig(r,map,path,kind,line){
 const sch=builderCheckDef(r,'node-config');
 if(sch)builderCheckWalk(r,map,sch,path,line,{kind,skip:['kind','stages'],nodeConfig:true});
 const stages=builderCheckGet(map,'stages');if(stages)builderCheckStages(r,stages,path.concat('stages'));
}
// R2a, R2b, R2c and R3 for one device, after inheritance.
function builderCheckDevice(r,t,name,entry){
 const nodeMap=builderCheckIsMap(entry.value)?entry.value:null,kindEntry=builderCheckKindEntry(t,nodeMap),path=['topology','nodes',name];
 let kind='';
 if(kindEntry){
  if(builderCheckIsScalar(kindEntry.value))kind=String(kindEntry.value.value);
  else if(r.schema)builderCheckAdd(r,'error',kindEntry.keyLine,'type',path.concat('kind'),'`kind` must be a kind name, not '+builderCheckNoun(builderCheckJsonType(kindEntry.value))+'.');
 }
 if(!kindEntry)builderCheckAdd(r,'error',entry.keyLine,'kind-missing',path.concat('kind'),'`'+builderCheckShow(name)+'` has no kind. Add `kind:` to the device (or to topology.defaults).');
 else if(kind&&r.schema){
  const kinds=builderCheckKindEnum(r);
  if(builderCheckAlias(kind)&&!kinds.includes(kind)){
   if(!r.aliases.has(kind)){
    r.aliases.add(kind);const long=BUILDER_KIND_LONG[kind]||'',k='`'+builderCheckShow(kind)+'`';
    const message=kind.startsWith(BUILDER_KIND_ALIASES.prefix)?(long?k+' is an old name containerlab still accepts; the current name is `'+long+'`.':k+' is an old name containerlab still accepts.'):(long?k+' is a short name for `'+long+'`; the long name is what the manager’s device catalog uses.':k+' is a short name containerlab accepts.');
    builderCheckAdd(r,'warning',kindEntry.keyLine,'kind-alias',path.concat('kind'),message);
   }
  }
  else if(kinds.length&&!kinds.includes(kind))builderCheckAdd(r,builderCheckExact(r),kindEntry.keyLine,'kind-unknown',path.concat('kind'),builderCheckClab(r)+' knows no kind `'+builderCheckShow(kind)+'`.'+builderCheckMean(kind,kinds));
 }
 const chain=builderCheckChain(t,nodeMap,kind);
 if(!BUILDER_NO_IMAGE_KINDS.includes(kind)&&!builderCheckSetting(chain,'image'))builderCheckAdd(r,'warning',entry.keyLine,'image-missing',path.concat('image'),'`'+builderCheckShow(name)+'` has no image. containerlab needs one to create the container; the deploy fails without it.');
 return {name,kind,chain,line:entry.keyLine};
}
// R6a for a device name: the schema's pattern and the manager's own rule (the review refuses `|`, the schema a leading `_`).
function builderCheckDeviceName(r,entry,nodesSch){
 const name=String(entry.key),shown='`'+builderCheckShow(name)+'`',path=['topology','nodes',name];
 const src=nodesSch&&nodesSch.patternProperties?Object.keys(nodesSch.patternProperties)[0]:'';
 const result=src?builderCheckMatch(src,name,false):true;
 if(result==='long'){builderCheckAdd(r,'warning',entry.keyLine,'too-long',path,'the device name is too long to check (more than 1,024 characters).');return false;}
 if(result!==false&&BUILDER_CHECK_MANAGER_NAME.test(name))return true;
 builderCheckAdd(r,'error',entry.keyLine,'pattern-hard',path,/^[A-Za-z0-9]/.test(name)?'the device name '+shown+' can only use letters, digits, dot, dash and underscore.':'the device name '+shown+' must start with a letter or digit.');
 return false;
}

// --- stages: R4 (stage names), R4b, R9a, R9b, R9c ----------------------------------------------------------
function builderCheckStages(r,stagesEntry,path){
 const stages=stagesEntry.value;
 if(builderCheckIsNull(stages))return;
 if(!builderCheckIsMap(stages)){if(r.schema)builderCheckAdd(r,'error',stagesEntry.keyLine,'type',path,'`stages` must be a mapping of stage names, not '+builderCheckNoun(builderCheckJsonType(stages))+'.');return;}
 for(const entry of stages.items){
  const stage=String(entry.key),here=path.concat(stage);
  if(!BUILDER_CHECK_STAGES.includes(stage)){
   if(r.schema)builderCheckAdd(r,builderCheckExact(r),entry.keyLine,'enum',here,'`'+builderCheckShow(stage)+'` is not a stage. The stages are '+builderCheckList(BUILDER_CHECK_STAGES)+'.'+builderCheckMean(stage,BUILDER_CHECK_STAGES));
   continue;
  }
  const body=entry.value;if(builderCheckIsNull(body))continue;
  if(!builderCheckIsMap(body)){if(r.schema)builderCheckAdd(r,'error',entry.keyLine,'type',here,'the stage `'+stage+'` must be a mapping with wait-for and exec, not '+builderCheckNoun(builderCheckJsonType(body))+'.');continue;}
  for(const part of body.items){
   if(part.key==='wait-for')builderCheckWaitFor(r,part,here.concat('wait-for'));
   else if(part.key==='exec')builderCheckExec(r,part,here.concat('exec'));
   else if(r.schema)builderCheckUnknown(r,part,here,['wait-for','exec']);
  }
 }
}
function builderCheckWaitFor(r,entry,path){
 const list=entry.value;if(builderCheckIsNull(list)||!r.schema)return;
 if(!builderCheckIsSeq(list)){builderCheckAdd(r,'error',entry.keyLine,'type',path,'`wait-for` must be a list of `- node: …` entries, not '+builderCheckNoun(builderCheckJsonType(list))+'.');return;}
 const seen=new Set();
 list.items.forEach((item,i)=>{
  const here=path.concat(String(i)),line=item.line||entry.keyLine;
  if(!builderCheckIsMap(item)){if(!builderCheckIsNull(item))builderCheckAdd(r,'error',line,'type',here,'each wait-for entry is a mapping with `node:` and `stage:`; '+(builderCheckIsScalar(item)?'`'+builderCheckShow(item.value)+'` on its own':builderCheckNoun(builderCheckJsonType(item)))+' is not one.');return;}
  const id=JSON.stringify(builderCheckPlain(item));if(seen.has(id))builderCheckAdd(r,'warning',line,'unique',here,'`wait-for` lists the same entry twice.');seen.add(id);
  for(const part of item.items)if(part.key!=='node'&&part.key!=='stage')builderCheckUnknown(r,part,here,['node','stage']);
  const stage=builderCheckGet(item,'stage');
  if(!stage||builderCheckIsNull(stage.value))builderCheckAdd(r,'warning',line,'wait-stage',here.concat('stage'),'this wait-for entry has no `stage:`.');
  else if(!BUILDER_CHECK_STAGES.includes(builderCheckText(stage.value)))builderCheckAdd(r,'warning',stage.keyLine,'wait-stage',here.concat('stage'),'`'+builderCheckShow(builderCheckText(stage.value)||builderCheckNoun(builderCheckJsonType(stage.value)))+'` is not a stage, so this wait may never end. Use '+builderCheckList(BUILDER_CHECK_STAGES,'or')+'.');
 });
}
// R9: containerlab 0.79.0 reads stage commands as a list of mappings (types.Execs), although its schema also allows
// on-enter/on-exit sections; the binary wins (§0). An entry without phase is fine (the binary defaults it to on-enter).
function builderCheckExec(r,entry,path){
 const list=entry.value,clab=builderCheckClab(r);if(builderCheckIsNull(list))return;
 if(builderCheckIsMap(list)){builderCheckAdd(r,'error',entry.keyLine,'exec-form',path,clab+' reads stage commands as a list of `- command: …` entries (with `phase: on-enter` or `on-exit` and `target: container` or `host`), not as on-enter/on-exit sections.');return;}
 if(!builderCheckIsSeq(list)){builderCheckAdd(r,'error',entry.keyLine,'exec-form',path,'stage commands are a list of `- command: …` entries; `'+builderCheckShow(list.value)+'` on its own is not one.');return;}
 list.items.forEach((item,i)=>{
  const here=path.concat(String(i)),line=item.line||entry.keyLine;
  if(builderCheckIsNull(item))return;
  if(!builderCheckIsMap(item)){builderCheckAdd(r,'error',line,'exec-entry',here,'each stage command is a mapping with `command:`; '+(builderCheckIsScalar(item)?'`'+builderCheckShow(item.value)+'` on its own':builderCheckNoun(builderCheckJsonType(item)))+' is not one.');return;}
  const command=builderCheckGet(item,'command');
  if(!command||builderCheckIsNull(command.value))builderCheckAdd(r,'error',line,'exec-entry',here.concat('command'),'each stage command is a mapping with `command:`; this one has none.');
  else if(!builderCheckIsScalar(command.value))builderCheckAdd(r,'error',command.keyLine,'exec-entry',here.concat('command'),'`command` must be the command line as text, not '+builderCheckNoun(builderCheckJsonType(command.value))+'.');
  const phase=builderCheckGet(item,'phase'),target=builderCheckGet(item,'target');
  if(phase&&!builderCheckIsNull(phase.value)&&!['on-enter','on-exit'].includes(builderCheckText(phase.value)))builderCheckAdd(r,'warning',phase.keyLine,'exec-entry',here.concat('phase'),'`'+builderCheckShow(builderCheckText(phase.value))+'` is not a phase. Use on-enter or on-exit.');
  if(target&&!builderCheckIsNull(target.value)&&!['container','host'].includes(builderCheckText(target.value)))builderCheckAdd(r,'warning',target.keyLine,'exec-entry',here.concat('target'),'`'+builderCheckShow(builderCheckText(target.value))+'` is not a target. Use container or host.');
  if(r.schema)for(const part of item.items)if(!['command','phase','target'].includes(part.key))builderCheckUnknown(r,part,here,['command','phase','target']);
 });
}

// --- the boot order graph: R8a, R8b, R8c, R8d ------------------------------------------------------------
// Every wait-for entry a device ends up with: its own and those containerlab adds from its group, its kind section
// and the defaults (decision 7).
function builderCheckWaits(devices){
 const waits=[];
 for(const d of devices)for(const link of d.chain){
  const stages=builderCheckValue(link.map,'stages');if(!builderCheckIsMap(stages))continue;
  for(const stage of stages.items){
   const list=builderCheckIsMap(stage.value)?builderCheckValue(stage.value,'wait-for'):undefined;if(!builderCheckIsSeq(list))continue;
   for(const item of list.items){
    if(!builderCheckIsMap(item))continue;
    const node=builderCheckGet(item,'node'),stageEntry=builderCheckGet(item,'stage');
    waits.push({waiter:d.name,target:node&&builderCheckIsScalar(node.value)&&!builderCheckIsNull(node.value)?String(node.value.value):'',line:node?node.keyLine:(item.line||stage.keyLine),
     stage:stageEntry?builderCheckText(stageEntry.value):'',stageLine:stageEntry?stageEntry.keyLine:(item.line||stage.keyLine),where:link.where,path:[]});
   }
  }
 }
 return waits;
}
function builderCheckGraph(r,devices){
 const names=devices.map(d=>d.name),byName=new Map(devices.map(d=>[d.name,d])),waits=builderCheckWaits(devices);
 for(const w of waits){
  const path=['topology','nodes',w.waiter,'stages'];
  if(!w.target){builderCheckAdd(r,'warning',w.line,'wait-node',path,'this wait-for entry names no device (`node:`), so it waits for nothing.');continue;}
  if(!byName.has(w.target)){builderCheckAdd(r,'error',w.line,'wait-node',path,'There is no device named `'+builderCheckShow(w.target)+'`.'+builderCheckMean(w.target,names));continue;}
  if(w.target===w.waiter){builderCheckAdd(r,'error',w.line,'wait-self',path,'A device cannot wait for itself (`'+builderCheckShow(w.waiter)+'` waits for `'+builderCheckShow(w.waiter)+'`'+(w.where?' through '+w.where:'')+').');continue;}
  const target=byName.get(w.target);
  if(w.stage==='healthy'&&BUILDER_NO_HEALTHCHECK_KINDS.includes(target.kind)&&!builderCheckHas(target.chain,'healthcheck')){
   const n='`'+builderCheckShow(target.name)+'`';
   builderCheckAdd(r,'warning',w.stageLine,'wait-health',path,target.kind==='linux'?n+' shows healthy only if its image defines a health check or the device has a `healthcheck:`; otherwise this wait never ends.':n+' has no health check, so it never reports healthy and this wait never ends. Wait for `create-links` or `configure` instead, or give '+n+' a `healthcheck:`.');
  }
 }
 // R8c: the loops of the graph waiting → waited-for, whatever the stages; one finding per loop (per strongly
 // connected group), at its first entry in text order.
 const edges=waits.filter(w=>w.target&&w.target!==w.waiter&&byName.has(w.target)),out=new Map(names.map(n=>[n,[]]));
 for(const e of edges)out.get(e.waiter).push(e);
 const index=new Map(),low=new Map(),onStack=new Set(),stack=[],groups=[];let counter=0;
 for(const start of names){
  if(index.has(start))continue;
  const work=[[start,0]];index.set(start,counter);low.set(start,counter);counter++;stack.push(start);onStack.add(start);
  while(work.length){
   const top=work[work.length-1],[v,i]=top,list=out.get(v);
   if(i<list.length){
    top[1]++;const w=list[i].target;
    if(!index.has(w)){index.set(w,counter);low.set(w,counter);counter++;stack.push(w);onStack.add(w);work.push([w,0]);}
    else if(onStack.has(w))low.set(v,Math.min(low.get(v),index.get(w)));
    continue;
   }
   work.pop();if(work.length){const parent=work[work.length-1][0];low.set(parent,Math.min(low.get(parent),low.get(v)));}
   if(low.get(v)===index.get(v)){const group=[];let w;do{w=stack.pop();onStack.delete(w);group.push(w);}while(w!==v);if(group.length>1)groups.push(new Set(group));}
  }
 }
 for(const group of groups){
  const inside=edges.filter(e=>group.has(e.waiter)&&group.has(e.target)).sort((a,b)=>a.line-b.line);
  const first=inside[0],back=new Map([[first.target,null]]),queue=[first.target];
  while(queue.length&&!back.has(first.waiter)){const v=queue.shift();for(const e of out.get(v))if(group.has(e.target)&&!back.has(e.target)){back.set(e.target,v);queue.push(e.target);}}
  // The way back from the waited-for device to the waiting one closes the loop: waiter → target → … → waiter.
  const tail=[];let v=first.waiter;while(v!==first.target&&back.has(v)&&tail.length<=group.size){tail.unshift(v);v=back.get(v);}
  const loop=[first.waiter,first.target,...tail.slice(0,-1),first.waiter];
  builderCheckAdd(r,'error',first.line,'wait-loop',['topology','nodes',first.waiter,'stages'],'Devices wait for each other in a loop ('+loop.map(builderCheckShow).join(' → ')+'). containerlab will not deploy the lab.');
 }
}

// --- links: R7a, R7b, R7c, R7d ----------------------------------------------------------------------------
function builderCheckLinkDef(r,type){
 const links=r.schema&&r.schema.properties&&r.schema.properties.topology?builderCheckResolve(r,r.schema.properties.topology):null;
 const items=links&&links.properties&&links.properties.links?builderCheckResolve(r,links.properties.links):null;
 const forms=items&&items.items?builderCheckResolve(r,items.items):null;
 for(const b of forms&&Array.isArray(forms.anyOf)?forms.anyOf:[]){const d=builderCheckResolve(r,b);const t=d&&d.properties?builderCheckResolve(r,d.properties.type):null;if(t&&t.const===type)return d;}
 return null;
}
function builderCheckLinks(r,linksEntry,names){
 const list=linksEntry.value;if(!builderCheckIsSeq(list))return;
 const used=new Map();
 const endpoint=(node,iface,line,linkLine,path,link)=>{
  if(!node)return;
  if(!BUILDER_CHECK_LINK_SPECIAL.includes(node)&&!names.includes(node))builderCheckAdd(r,'error',line,'link-node',path,'the link endpoint `'+builderCheckShow(node)+'` is not a device in topology.nodes.');
  if(!iface)return;
  const id=node+':'+iface,first=used.get(id);
  // Both ends of one link the same: R7a has said so.
  if(first&&first.link!==link)builderCheckAdd(r,'warning',line,'link-duplicate',path,'`'+builderCheckShow(id)+'` is already used by the link on line '+first.line+'.');
  else if(!first)used.set(id,{line:linkLine,link});
 };
 list.items.forEach((link,i)=>{
  const path=['topology','links',String(i)],line=link.line||linksEntry.keyLine;
  const brief='a link needs exactly two endpoints as `device:interface`.';
  if(!builderCheckIsMap(link)){if(!builderCheckIsNull(link))builderCheckAdd(r,'error',line,'link-brief',path,brief);return;}
  const typeEntry=builderCheckGet(link,'type');
  if(!typeEntry||builderCheckIsNull(typeEntry.value)){
   const ends=builderCheckGet(link,'endpoints'),items=ends&&builderCheckIsSeq(ends.value)?ends.value.items:null,at=ends?ends.keyLine:line;
   const texts=items?items.map(e=>builderCheckIsScalar(e)&&builderCheckTag(e)==='str'?String(e.value):null):null;
   if(!texts||texts.length!==2||texts.some(t=>t===null||!/^\S+:\S+$/.test(t)))builderCheckAdd(r,'error',at,'link-brief',path.concat('endpoints'),brief);
   else if(texts[0]===texts[1])builderCheckAdd(r,'error',at,'link-brief',path.concat('endpoints'),'both endpoints of this link are `'+builderCheckShow(texts[0])+'`; a link connects two different interfaces.');
   (items||[]).forEach((e,j)=>{
    const here=path.concat('endpoints',String(j)),eline=e.line||at;
    if(builderCheckIsScalar(e)&&!builderCheckIsNull(e)){const t=String(e.value),k=t.indexOf(':');if(k>0)endpoint(t.slice(0,k),t.slice(k+1),eline,line,here,i);}
    else if(builderCheckIsMap(e))endpoint(builderCheckText(builderCheckValue(e,'node')),builderCheckText(builderCheckValue(e,'interface')),eline,line,here,i);
   });
   if(r.schema){const def=builderCheckDef(r,'link-config-short');if(def)builderCheckLinkKeys(r,link,def,path,'a link',['endpoints']);}
   return;
  }
  // The long forms: endpoints (veth, veth-stitch) or one endpoint (the others).
  const ends=builderCheckGet(link,'endpoints'),one=builderCheckGet(link,'endpoint');
  const each=(e,j,here)=>{if(builderCheckIsMap(e))endpoint(builderCheckText(builderCheckValue(e,'node')),builderCheckText(builderCheckValue(e,'interface')),e.line||line,line,here,i);};
  if(ends&&builderCheckIsSeq(ends.value))ends.value.items.forEach((e,j)=>each(e,j,path.concat('endpoints',String(j))));
  if(one)each(one.value,0,path.concat('endpoint'));
  if(!r.schema)return;
  const type=builderCheckText(typeEntry.value);
  if(!builderCheckIsScalar(typeEntry.value)||!BUILDER_CHECK_LINK_TYPES.includes(type)){
   builderCheckAdd(r,builderCheckExact(r),typeEntry.keyLine,'link-type',path.concat('type'),'`'+builderCheckShow(type||builderCheckNoun(builderCheckJsonType(typeEntry.value)))+'` is not a link type. The types are '+builderCheckList(BUILDER_CHECK_LINK_TYPES)+'.'+builderCheckMean(type,BUILDER_CHECK_LINK_TYPES));
   return;
  }
  const def=builderCheckLinkDef(r,type);if(!def)return;
  const required=(Array.isArray(def.required)?def.required:[]).filter(k=>k!=='type');
  const a='a `'+type+'` link';
  if(required.some(k=>{const e=builderCheckGet(link,k);return !e||builderCheckIsNull(e.value);}))builderCheckAdd(r,builderCheckExact(r),line,'link-type',path,a+' needs '+builderCheckList(required.map(k=>'`'+k+'`'))+'.');
  const epDef=builderCheckDef(r,'link-endpoint'),epKnown=epDef&&epDef.properties?Object.keys(epDef.properties):[];
  const checkEndpoint=(e,here,eline,sentence)=>{
   if(builderCheckIsNull(e))return;
   if(!builderCheckIsMap(e)||['node','interface'].some(k=>builderCheckIsNull(builderCheckValue(e,k)))){builderCheckAdd(r,builderCheckExact(r),eline,'link-type',here,sentence);if(!builderCheckIsMap(e))return;}
   for(const part of e.items){
    if(part.key==='node'||part.key==='interface')continue;
    if(epDef&&epDef.properties&&Object.prototype.hasOwnProperty.call(epDef.properties,part.key))builderCheckWalk(r,part.value,epDef.properties[part.key],here.concat(part.key),part.keyLine);
    else builderCheckUnknown(r,part,here,epKnown);
   }
  };
  if(def.properties&&def.properties.endpoints){
   const sentence=a+' needs exactly two endpoints, each with `node:` and `interface:`.';
   if(ends&&!builderCheckIsNull(ends.value)){
    if(!builderCheckIsSeq(ends.value)||ends.value.items.length!==2)builderCheckAdd(r,builderCheckExact(r),ends.keyLine,'link-type',path.concat('endpoints'),sentence);
    if(builderCheckIsSeq(ends.value))ends.value.items.forEach((e,j)=>checkEndpoint(e,path.concat('endpoints',String(j)),e.line||ends.keyLine,sentence));
   }
  }
  else if(one&&!builderCheckIsNull(one.value))checkEndpoint(one.value,path.concat('endpoint'),one.keyLine,'the endpoint of '+a+' is a mapping with `node:` and `interface:`.');
  builderCheckLinkKeys(r,link,def,path,a,['type','endpoints','endpoint']);
 });
}
// A link's other keys: unknown ones (R1 at the link level), known ones through the walker (mtu, ipv4, mac, vni, …).
function builderCheckLinkKeys(r,link,def,path,where,owned){
 const props=def.properties||{},known=Object.keys(props);
 for(const part of link.items){
  if(owned.includes(part.key))continue;
  if(Object.prototype.hasOwnProperty.call(props,part.key))builderCheckWalk(r,part.value,props[part.key],path.concat(part.key),part.keyLine);
  else builderCheckUnknown(r,part,path,known,where);
 }
}

// --- the check ------------------------------------------------------------------------------------------
// builderCheck(tree, schema, context) → [{severity, line, message, code, path}], sorted by line then severity, at
// most BUILDER_CHECK_LIMIT items plus one closing "… and N more". With schema === null only the rules that need no
// schema run (R0, R2a, R3, R7a/c/d, R8a–d, R9a/b), so the list works before the schema arrives and when its fetch
// failed. `message` carries no "Line N:" prefix: the panel writes the line beside it.
function builderCheck(tree,schema,context){
 if(!tree||typeof tree!=='object')return [];
 const r=builderCheckStart(schema,context);
 builderCheckRoot(r,tree);
 return builderCheckFinish(r);
}
function builderCheckRoot(r,tree){
 const shape=(message,line,path)=>builderCheckAdd(r,'error',line,'shape',path,message);
 if(!builderCheckIsMap(tree)){shape('A topology file is a mapping with name: and topology: at the top.',tree.line,[]);return;}
 const topo=builderCheckGet(tree,'topology');
 if(r.schema)builderCheckWalk(r,tree,r.schema,[],tree.line,{skip:['topology'],optional:['topology']});
 if(!topo){shape('The file has no topology: section.',tree.line,['topology']);return;}
 if(!builderCheckIsMap(topo.value)){shape('topology: must be a mapping (nodes:, links:, …).',topo.value&&topo.value.line||topo.keyLine,['topology']);return;}
 builderCheckTopology(r,topo);
}
function builderCheckTopology(r,topo){
 const t=topo.value,path=['topology'];
 const nodes=builderCheckGet(t,'nodes'),links=builderCheckGet(t,'links');
 if(nodes&&!(builderCheckIsMap(nodes.value)||builderCheckIsNull(nodes.value))){builderCheckAdd(r,'error',nodes.value.line||nodes.keyLine,'shape',['topology','nodes'],'topology.nodes must be a mapping of device names.');return;}
 if(links&&!(builderCheckIsSeq(links.value)||builderCheckIsNull(links.value))){builderCheckAdd(r,'error',links.value.line||links.keyLine,'shape',['topology','links'],'topology.links must be a list.');return;}
 const topoSch=r.schema&&r.schema.properties?builderCheckResolve(r,r.schema.properties.topology):null;
 const owned=['nodes','links','kinds','groups','defaults'];
 if(topoSch)builderCheckWalk(r,t,topoSch,path,topo.keyLine,{skip:owned,optional:['nodes']});
 const props=topoSch&&topoSch.properties?topoSch.properties:{};
 // defaults, kinds and groups: each a node-config mapping, checked once where it is written.
 const defaults=builderCheckGet(t,'defaults');
 if(defaults&&!builderCheckIsNull(defaults.value)){
  if(builderCheckIsMap(defaults.value))builderCheckNodeConfig(r,defaults.value,['topology','defaults'],builderCheckText(builderCheckValue(defaults.value,'kind')),defaults.keyLine);
  else if(r.schema)builderCheckWrongType(r,defaults.value,{type:'object'},['topology','defaults'],defaults.keyLine);
 }
 const kinds=builderCheckGet(t,'kinds');
 if(kinds&&!builderCheckIsNull(kinds.value)){
  if(!builderCheckIsMap(kinds.value)){if(r.schema)builderCheckWrongType(r,kinds.value,{type:'object'},['topology','kinds'],kinds.keyLine);}
  else{
   const kindsSch=props.kinds?builderCheckResolve(r,props.kinds):null,listed=kindsSch&&kindsSch.properties?Object.keys(kindsSch.properties):[];
   for(const entry of kinds.value.items){
    const name=String(entry.key);
    if(r.schema&&kindsSch&&kindsSch.additionalProperties===false&&!listed.includes(name)&&!builderCheckAlias(name))builderCheckUnknown(r,entry,['topology','kinds'],listed);
    if(builderCheckIsMap(entry.value))builderCheckNodeConfig(r,entry.value,['topology','kinds',name],name,entry.keyLine);
    else if(!builderCheckIsNull(entry.value)&&r.schema)builderCheckWrongType(r,entry.value,{type:'object'},['topology','kinds',name],entry.keyLine);
   }
  }
 }
 const groups=builderCheckGet(t,'groups');
 if(groups&&!builderCheckIsNull(groups.value)){
  if(!builderCheckIsMap(groups.value)){if(r.schema)builderCheckWrongType(r,groups.value,{type:'object'},['topology','groups'],groups.keyLine);}
  else for(const entry of groups.value.items){
   const name=String(entry.key);
   if(builderCheckIsMap(entry.value))builderCheckNodeConfig(r,entry.value,['topology','groups',name],builderCheckText(builderCheckValue(entry.value,'kind')),entry.keyLine);
   else if(!builderCheckIsNull(entry.value)&&r.schema)builderCheckWrongType(r,entry.value,{type:'object'},['topology','groups',name],entry.keyLine);
  }
 }
 // The devices: their names (R6a), their settings, then the rules that need inheritance.
 const devices=[],nodesSch=props.nodes?builderCheckResolve(r,props.nodes):null;
 const names=nodes&&builderCheckIsMap(nodes.value)?nodes.value.items.map(e=>String(e.key)):[];
 for(const entry of nodes&&builderCheckIsMap(nodes.value)?nodes.value.items:[]){
  const name=String(entry.key),here=['topology','nodes',name];
  if(r.schema)builderCheckDeviceName(r,entry,nodesSch);
  // A device that is not a mapping is one type error, not a missing kind and image as well.
  if(!builderCheckIsMap(entry.value)&&!builderCheckIsNull(entry.value)&&r.schema){
   builderCheckAdd(r,'error',entry.keyLine,'type',here,'the device `'+builderCheckShow(name)+'` must be a mapping of settings, not '+builderCheckNoun(builderCheckJsonType(entry.value))+'.');
   devices.push({name,kind:'',chain:[],line:entry.keyLine});continue;
  }
  const device=builderCheckDevice(r,t,name,entry);devices.push(device);
  if(builderCheckIsMap(entry.value))builderCheckNodeConfig(r,entry.value,here,device.kind,entry.keyLine);
 }
 if(links)builderCheckLinks(r,links,names);
 builderCheckGraph(r,devices);
}
// Sorted by line, errors first on a line; duplicates (an inherited entry reported for every device) once; capped.
function builderCheckFinish(r){
 const seen=new Set(),list=[];
 for(const f of r.out){const id=f.code+'|'+f.line+'|'+f.message;if(seen.has(id))continue;seen.add(id);list.push(f);}
 list.sort((a,b)=>a.line-b.line||(a.severity===b.severity?0:a.severity==='error'?-1:1));
 if(list.length<=BUILDER_CHECK_LIMIT)return list;
 const rest=list.slice(BUILDER_CHECK_LIMIT),errors=rest.filter(f=>f.severity==='error').length;
 return list.slice(0,BUILDER_CHECK_LIMIT).concat([{severity:errors?'error':'warning',line:0,message:'… and '+rest.length+' more.',code:'more',path:[],more:{errors,warnings:rest.length-errors}}]);
}
// builderCheckSummary(list) → {errors, warnings, text}: "2 errors, 1 warning", "1 warning", "No problems found".
function builderCheckSummary(list){
 let errors=0,warnings=0;
 for(const f of Array.isArray(list)?list:[]){
  if(f&&f.code==='more'&&f.more){errors+=f.more.errors||0;warnings+=f.more.warnings||0;continue;}
  if(f&&f.severity==='error')errors++;else if(f&&f.severity==='warning')warnings++;
 }
 const parts=[];if(errors)parts.push(errors+' error'+(errors===1?'':'s'));if(warnings)parts.push(warnings+' warning'+(warnings===1?'':'s'));
 return {errors,warnings,text:parts.length?parts.join(', '):'No problems found'};
}

// --- which schema: §2.3 ------------------------------------------------------------------------------------
function builderSchemaParts(v){const m=/^(\d+)\.(\d+)\.(\d+)/.exec(String(v||''));return m?[Number(m[1]),Number(m[2]),Number(m[3])]:null;}
function builderSchemaCompare(a,b){for(let i=0;i<3;i++)if(a[i]!==b[i])return a[i]<b[i]?-1:1;return 0;}
// builderSchemaChoice(vmVersion, available) → {schemaVersion, exact, reason, vmVersion, caption}. `exact` needs the
// whole VM string to equal a vendored version; the fetch URL is built from the list entry, never from the VM's string.
function builderSchemaChoice(vmVersion,available){
 const vm=typeof vmVersion==='string'?vmVersion:'';
 const list=(Array.isArray(available)?available:BUILDER_SCHEMA_VERSIONS).filter(v=>typeof v==='string'&&/^\d+\.\d+\.\d+$/.test(v)).slice().sort((a,b)=>builderSchemaCompare(builderSchemaParts(a),builderSchemaParts(b)));
 if(!list.length)return {schemaVersion:'',exact:false,reason:'none',vmVersion:vm,caption:'The manager carries no topology schema, so settings and kinds are not checked; links and boot order still are.'};
 const newest=list[list.length-1],oldest=list[0],parts=builderSchemaParts(vm);
 if(!parts)return {schemaVersion:newest,exact:false,reason:'unknown',vmVersion:vm,caption:'The VM’s containerlab version is not known yet (not connected, or the VM’s manager tools are older), so the text is checked against the containerlab '+newest+' schema; unknown settings are shown as warnings.'};
 if(list.includes(vm))return {schemaVersion:vm,exact:true,reason:'exact',vmVersion:vm,caption:'Checked against containerlab '+vm+', the version on this VM.'};
 if(builderSchemaCompare(parts,builderSchemaParts(newest))>0)return {schemaVersion:newest,exact:false,reason:'newer',vmVersion:vm,caption:'Checked against the containerlab '+newest+' schema; this VM runs '+vm+'. A setting added since then is shown as a warning, not an error.'};
 if(builderSchemaCompare(parts,builderSchemaParts(oldest))<0)return {schemaVersion:oldest,exact:false,reason:'older',vmVersion:vm,caption:'Checked against the containerlab '+oldest+' schema; this VM runs '+vm+', older than any schema the manager carries. containerlab itself reports settings it does not know when the lab is deployed.'};
 const below=list.filter(v=>builderSchemaCompare(builderSchemaParts(v),parts)<=0).pop();
 return {schemaVersion:below,exact:false,reason:'between',vmVersion:vm,caption:'Checked against the containerlab '+below+' schema; this VM runs '+vm+'.'};
}

// --- key help on the caret: §4.3 ---------------------------------------------------------------------------
// The schema of a key path: properties, patternProperties and items, through local references and the branches of
// anyOf/oneOf/allOf (the branch that names the next key wins).
function builderKeyHelpSchema(r,path){
 let sch=r.schema;
 for(const raw of path){
  const step=String(raw);sch=builderCheckResolve(r,sch);if(!sch)return null;
  const candidates=[sch];for(const word of ['anyOf','oneOf','allOf'])if(Array.isArray(sch[word]))for(const b of sch[word]){const c=builderCheckResolve(r,b);if(c)candidates.push(c);}
  let next=null;
  if(builderCheckIsIndex(step)){for(const c of candidates){if(Array.isArray(c.prefixItems)&&Number(step)<c.prefixItems.length){next=c.prefixItems[Number(step)];break;}if(c.items&&typeof c.items==='object'&&!Array.isArray(c.items)){next=c.items;break;}}}
  else{
   const name=Object.prototype.hasOwnProperty.call(BUILDER_DEPRECATED_KEYS,step)?BUILDER_DEPRECATED_KEYS[step]:step;
   for(const c of candidates)if(c.properties&&Object.prototype.hasOwnProperty.call(c.properties,step)){next=c.properties[step];break;}
   if(!next)for(const c of candidates)if(c.properties&&Object.prototype.hasOwnProperty.call(c.properties,name)){next=c.properties[name];break;}
   if(!next)for(const c of candidates){const p=builderCheckPatternProp(c,step);if(p!==undefined){next=p;break;}}
  }
  if(!next)return null;sch=next;
 }
 sch=builderCheckResolve(r,sch);if(!sch)return null;
 // A key whose schema is only a choice of forms (a device: null or node-config) takes the description of the form that has one.
 if(typeof sch.description!=='string'&&typeof sch.markdownDescription!=='string')for(const word of ['oneOf','anyOf'])if(Array.isArray(sch[word]))for(const b of sch[word]){const c=builderCheckResolve(r,b);if(c&&(typeof c.description==='string'||typeof c.markdownDescription==='string'))return c;}
 return sch;
}
// builderKeyHelp(tree, schema, line) → {key, path, description, url} for the key on a 1-based line, or null. The
// link is the first containerlab.dev link of the key's markdownDescription; any other host gives no link.
function builderKeyHelp(tree,schema,line){
 if(!tree||!schema||typeof schema!=='object'||!(Number(line)>0))return null;
 const r=builderCheckStart(schema,{}),stack=[[tree,[]]];let found=null;
 while(stack.length&&!found){
  const [node,path]=stack.pop();
  if(builderCheckIsMap(node)){
   for(const item of node.items)if(item&&item.keyLine===Number(line)){found={key:String(item.key),path:path.concat(String(item.key))};break;}
   if(!found)for(let i=node.items.length-1;i>=0;i--){const item=node.items[i];if(item&&item.value&&typeof item.value==='object')stack.push([item.value,path.concat(String(item.key))]);}
  }
  else if(builderCheckIsSeq(node))for(let i=node.items.length-1;i>=0;i--){const item=node.items[i];if(item&&typeof item==='object')stack.push([item,path.concat(String(i))]);}
 }
 if(!found)return null;
 const sch=builderKeyHelpSchema(r,found.path);if(!sch)return null;
 const description=typeof sch.description==='string'?sch.description.trim():'';
 const m=typeof sch.markdownDescription==='string'?/\]\((https:\/\/containerlab\.dev\/[^)\s]*)\)/.exec(sch.markdownDescription):null;
 const url=m?m[1]:'';
 if(!description&&!url)return null;
 return {key:found.key,path:found.path,description,url};
}
