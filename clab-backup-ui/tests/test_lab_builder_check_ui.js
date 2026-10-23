// The lab builder's topology check (app/static/lab-builder-check.js; docs/parity-campaign/C08-DESIGN.md §2.2, §2.3, §3,
// §4.3 and §6.1). The script is loaded into a bare context (no document, no fetch, no timers) like the browser loads it
// beside the other builder scripts, and checked against the vendored containerlab 0.79.0 schema read from disk.
// Trees are stated as object literals: located() numbers every key and item in the order a block YAML prints them, so a
// test reads a finding's line from the same walk (a scalar shares its key's line; a list item mapping starts on the dash line).
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const STATIC=path.join(__dirname,'../app/static');
const SOURCE=fs.readFileSync(path.join(STATIC,'lab-builder-check.js'),'utf8');
const SCHEMA=JSON.parse(fs.readFileSync(path.join(STATIC,'clab-schema/0.79.0.json'),'utf8'));
function load(){const context=vm.createContext({});vm.runInContext(SOURCE,context,{filename:'lab-builder-check.js'});return context;}
const C=load();
const isObj=v=>v!==null&&typeof v==='object'&&!Array.isArray(v);
function located(root){
 let n=0;
 const scalar=(v,line)=>({kind:'scalar',line,value:v,tag:v===null?'null':typeof v==='boolean'?'bool':typeof v==='number'?(Number.isInteger(v)?'int':'float'):'str'});
 const value=(v,keyLine)=>{if(isObj(v)&&Object.keys(v).length)return map(v,false);if(Array.isArray(v)&&v.length)return seq(v);if(Array.isArray(v))return {kind:'seq',line:keyLine,items:[]};if(isObj(v))return {kind:'map',line:keyLine,items:[]};return scalar(v,keyLine);};
 const map=(o,first)=>{const items=[];let line=0;Object.entries(o).forEach(([k,v],i)=>{const keyLine=i===0&&first?n:++n;if(i===0)line=keyLine;items.push({key:k,keyLine,value:value(v,keyLine)});});return {kind:'map',line,items};};
 const seq=a=>({kind:'seq',line:n+1,items:a.map(v=>{if(isObj(v)&&Object.keys(v).length){++n;return map(v,true);}++n;if(Array.isArray(v)&&v.length){const line=n,s=seq(v);s.line=line;return s;}return value(v,n);})});
 if(isObj(root)&&Object.keys(root).length)return map(root,false);
 return value(root,1);
}
const EXACT={version:'0.79.0',schemaVersion:'0.79.0',exact:true},LOOSE={version:'0.81.0',schemaVersion:'0.79.0',exact:false};
const plain=x=>JSON.parse(JSON.stringify(x));
const check=(doc,ctx=EXACT,schema=SCHEMA)=>plain(C.builderCheck(located(doc),schema,ctx));
const brief=f=>[f.line,f.severity,f.code,f.message];
// A lab around some device settings: one device `a` (cEOS by default) plus `others`.
const lab=(a,others={},extra={})=>({name:'lab',topology:Object.assign({nodes:Object.assign({a:Object.assign({kind:'arista_ceos',image:'ceos:4.33'},a)},others)},extra)});
const only=(doc,ctx)=>{const list=check(doc,ctx);assert.equal(list.length,1,JSON.stringify(list,null,1));return list[0];};
// The §4.5 example: the switch boots first, the router waits for it to report healthy.
const EXAMPLE={name:'juniper-pair',topology:{nodes:{vsw:{kind:'juniper_vjunosswitch',image:'n24l/vjunos-switch:23.2R1.14'},
 vrt:{kind:'juniper_vjunosrouter',image:'n24l/juniper_vjunos-router:26.2R1.7',stages:{create:{'wait-for':[{node:'vsw',stage:'healthy'}]}}}},
 links:[{endpoints:['vsw:ge-0/0/0','vrt:ge-0/0/0']}]}};

// ---- loading and shape of the module ----------------------------------------------------------------------
test('the script loads in a bare context and exposes the four functions of the contract',()=>{
 const c=load();
 for(const name of ['builderCheck','builderCheckSummary','builderKeyHelp','builderSchemaChoice','builderCheckSelfTest'])assert.equal(typeof c[name],'function',name);
 assert.deepEqual(plain(vm.runInContext('BUILDER_SCHEMA_VERSIONS',c)),['0.79.0']);
 assert.equal(vm.runInContext('BUILDER_CHECK_LIMIT',c),200);
});
test('the script reaches no browser or network API and builds no code: student text is only ever the subject of RegExp.test',()=>{
 const code=SOURCE.split('\n').filter(line=>!/^\s*\/\//.test(line)).join('\n');
 for(const word of [/\bfetch\s*\(/,/\bdocument\b/,/\bwindow\b/,/\blocalStorage\b/,/\bXMLHttpRequest\b/,/\beval\s*\(/,/\bnew Function\b/,/\bFunction\s*\(/,/innerHTML/,/\bsetTimeout\b/,/\bimport\s*\(/])assert.doesNotMatch(code,word,String(word));
 // Every RegExp built at run time is built from a schema pattern (builderCheckRegex), never from a tree value.
 assert.deepEqual([...code.matchAll(/new RegExp\(([^,]*),/g)].map(m=>m[1]),['src']);
 const regex=SOURCE.slice(SOURCE.indexOf('function builderCheckRegex('),SOURCE.indexOf('function builderCheckMatch('));assert.match(regex,/new RegExp\(src,src\.includes\('\\\\p\{'\)\?'u':''\)/);
});
test('the script declares no top-level name another lab builder script declares, and keeps its own prefixes',()=>{
 const html=fs.readFileSync(path.join(STATIC,'lab-builder.html'),'utf8');
 const others=[...html.matchAll(/<script[^>]*\ssrc="\/static\/([^"?]+\.js)\?v=[^"]*"/g)].map(m=>m[1]).filter(n=>n!=='lab-builder-check.js');
 assert.ok(others.includes('lab-builder-page.js')&&others.includes('lab-builder-yaml.js'),others.join(' '));
 const declared=text=>new Set([...text.matchAll(/^(?:async\s+)?(?:function\s*\*?\s*|const\s+|let\s+|var\s+|class\s+)([A-Za-z_$][\w$]*)/gm)].map(m=>m[1]));
 const mine=declared(SOURCE);assert.ok(mine.size>20);
 for(const name of others){const theirs=declared(fs.readFileSync(path.join(STATIC,name),'utf8'));for(const n of mine)assert.ok(!theirs.has(n),n+' is also declared by '+name);}
 for(const n of mine)assert.match(n,/^(builderCheck|builderSchema|builderKeyHelp|BUILDER_)/,n);
 // The page's own advisory check (S3) is builderCheckStatus: this script leaves that name to it.
 assert.ok(!mine.has('builderCheckStatus'));
 // And in one context with the panel and the page script, as the browser runs them.
 const context=vm.createContext({console});
 for(const name of ['lab-builder-page.js','lab-builder-yaml.js'])vm.runInContext(fs.readFileSync(path.join(STATIC,name),'utf8'),context);
 vm.runInContext(SOURCE,context);assert.equal(typeof context.builderCheck,'function');
});

// ---- the example and the shape rules -----------------------------------------------------------------------
test('the stage example of the help has no finding, with and without the schema, exact or not',()=>{
 const t=located(EXAMPLE);
 assert.equal(t.items[1].value.items[0].value.items[1].value.items[2].value.items[0].value.items[0].value.items[0].items[0].keyLine,13,'wait-for[0].node on line 13, as the adapter reports it');
 assert.deepEqual(check(EXAMPLE),[]);assert.deepEqual(check(EXAMPLE,LOOSE),[]);assert.deepEqual(check(EXAMPLE,EXACT,null),[]);
});
test('R0: the shape rules of yamlFlaw, with its wording; a root that is a list yields R0 only',()=>{
 const t={kind:'seq',line:1,items:[{kind:'scalar',line:1,value:'a',tag:'str'}]};
 assert.deepEqual(plain(C.builderCheck(t,SCHEMA,EXACT)).map(brief),[[1,'error','shape','A topology file is a mapping with name: and topology: at the top.']]);
 assert.deepEqual(plain(C.builderCheck(t,null,EXACT)).map(brief),[[1,'error','shape','A topology file is a mapping with name: and topology: at the top.']]);
 assert.deepEqual(check({name:'x'}).map(brief),[[1,'error','shape','The file has no topology: section.']]);
 assert.deepEqual(check({name:'x',topology:[1]}).map(brief),[[3,'error','shape','topology: must be a mapping (nodes:, links:, …).']]);
 assert.deepEqual(check({name:'x',topology:{nodes:['a']}}).map(brief),[[4,'error','shape','topology.nodes must be a mapping of device names.']]);
 assert.deepEqual(check({name:'x',topology:{nodes:{},links:{a:1}}}).map(brief),[[5,'error','shape','topology.links must be a list.']]);
 assert.deepEqual(plain(C.builderCheck(null,SCHEMA,EXACT)),[]);
});
test('an empty or missing device list is not reported (the review says so before saving)',()=>{
 assert.deepEqual(check({name:'x',topology:{nodes:{}}}),[]);assert.deepEqual(check({name:'x',topology:{nodes:null}}),[]);assert.deepEqual(check({name:'x',topology:{links:[]}}),[]);
});

// ---- R1: unknown keys -----------------------------------------------------------------------------------------
test('R1 on a device: with a suggestion, without one, error when exact, warning otherwise (same tree)',()=>{
 const doc=lab({imge:'x'});
 assert.deepEqual(brief(only(doc)),[7,'error','unknown-key','`imge` is not a device setting containerlab 0.79.0 knows. Did you mean `image`?']);
 assert.deepEqual(brief(only(doc,LOOSE)),[7,'warning','unknown-key','`imge` is not a device setting containerlab 0.79.0 knows. Did you mean `image`?']);
 assert.deepEqual(brief(only(lab({frobnicate:1}))),[7,'error','unknown-key','`frobnicate` is not a device setting containerlab 0.79.0 knows.']);
 assert.deepEqual(only(lab({Image:'x'})).message.endsWith('Did you mean `image`?'),true,'case differs only');
 assert.deepEqual(only(lab({'startup_config':'x'})).message.endsWith('Did you mean `startup-config`?'),true,'_ for -');
 assert.deepEqual(only(lab({imge:'x'})).path,['topology','nodes','a','imge']);
});
test('R1 at the top level lists the sections; a missing context is never exact',()=>{
 const f=only({name:'x',topolgy:{},topology:{nodes:{}}});
 assert.deepEqual(brief(f),[2,'error','unknown-key','`topolgy` is not a top-level section (name, prefix, mgmt, topology, settings, debug). Did you mean `topology`?']);
 assert.deepEqual(brief(only({name:'x',foo:1,topology:{nodes:{}}})),[2,'error','unknown-key','`foo` is not a top-level section (name, prefix, mgmt, topology, settings, debug).']);
 assert.equal(plain(C.builderCheck(located({name:'x',foo:1,topology:{nodes:{}}}),SCHEMA))[0].severity,'warning');
});
test('R1 is an error only at a level containerlab 0.79.0 was seen refusing (root, mgmt, node, stages, wait-for), else a warning',()=>{
 const cases=[
  [{name:'x',mgmt:{network:'n',foo:1},topology:{nodes:{}}},'error','`foo` is not a mgmt setting containerlab 0.79.0 knows.'],
  [{name:'x',topology:{nodes:{},foo:1}},'warning','`foo` is not a section of topology (nodes, groups, kinds, defaults, links).'],
  [lab({},{},{defaults:{imge:'x'}}),'warning','`imge` is not a device setting containerlab 0.79.0 knows (in topology.defaults). Did you mean `image`?'],
  [lab({},{},{kinds:{arista_ceos:{imge:'x'}}}),'warning','`imge` is not a device setting containerlab 0.79.0 knows (in topology.kinds.arista_ceos). Did you mean `image`?'],
  [lab({},{},{kinds:{nosuch:{}}}),'warning','`nosuch` is not a kind containerlab 0.79.0 takes settings for in topology.kinds.'],
  [lab({},{},{groups:{g1:{imge:'x'}}}),'warning','`imge` is not a device setting containerlab 0.79.0 knows (in topology.groups.g1). Did you mean `image`?'],
  [lab({healthcheck:{test:['true'],foo:1}}),'warning','`foo` is not a setting containerlab 0.79.0 knows in topology.nodes.a.healthcheck.'],
  [lab({dns:{servers:['1.1.1.1'],foo:1}}),'warning','`foo` is not a setting containerlab 0.79.0 knows in topology.nodes.a.dns.'],
  [lab({certificate:{issue:true,foo:1}}),'warning','`foo` is not a setting containerlab 0.79.0 knows in topology.nodes.a.certificate.'],
  [lab({config:{vars:{a:1},foo:1}}),'warning','`foo` is not a setting containerlab 0.79.0 knows in topology.nodes.a.config.'],
  [lab({extras:{foo:1}}),'warning','`foo` is not a setting containerlab 0.79.0 knows in topology.nodes.a.extras.'],
  [{name:'x',settings:{foo:1},topology:{nodes:{}}},'warning','`foo` is not a setting containerlab 0.79.0 knows in settings.'],
  [{name:'x',settings:{'certificate-authority':{'key-size':2048,foo:1}},topology:{nodes:{}}},'warning','`foo` is not a setting containerlab 0.79.0 knows in settings.certificate-authority.'],
  [lab({stages:{create:{foo:1}}}),'warning','`foo` is not a setting of a stage; a stage takes wait-for and exec.'],
  [lab({stages:{create:{exec:[{command:'ls',foo:1}]}}}),'warning','`foo` is not a setting of a stage command (command, phase, target).'],
  [lab({},{b:{kind:'linux',image:'alpine'}},{links:[{type:'veth',endpoints:[{node:'a',interface:'e1'},{node:'b',interface:'e1'}],foo:1}]}),'warning','`foo` is not a setting of a `veth` link.'],
  [lab({},{},{links:[{type:'host',endpoint:{node:'a',interface:'e1',foo:1},'host-interface':'h1'}]}),'warning','`foo` is not a setting of a link endpoint (node, interface, mac, ipv4, ipv6, vars).'],
  [lab({},{b:{kind:'linux',image:'alpine'}},{links:[{endpoints:['a:e1','b:e1'],foo:1}]}),'warning','`foo` is not a setting of a link.'],
 ];
 for(const [doc,severity,message] of cases){const f=only(doc,EXACT);assert.equal(f.code,'unknown-key',message);assert.equal(f.severity,severity,message);assert.equal(f.message,message);}
});
test('the keys containerlab 0.79.0 reads although its schema omits them: position silent, username/password and the renamed keys warnings, never R1',()=>{
 for(const where of [d=>lab(d),d=>lab({},{},{defaults:d}),d=>lab({},{},{kinds:{arista_ceos:d}}),d=>lab({group:'g'},{},{groups:{g:d}})])assert.deepEqual(check(where({position:'1,2'})),[]);
 const login=only(lab({username:'admin'}));
 assert.deepEqual(brief(login),[7,'warning','legacy-login','`username` is an old place for the login; containerlab still reads it, the current form is `credentials: {username: …, password: …}`.']);
 assert.equal(only(lab({password:'x'})).code,'legacy-login');
 assert.deepEqual(brief(only(lab({mgmt_ipv4:'172.20.20.5'}))),[7,'warning','renamed-key','`mgmt_ipv4` is an old name containerlab still accepts; the current name is `mgmt-ipv4`.']);
 // The value is still checked under the current name's rules.
 const both=check(lab({mgmt_ipv6:'not-an-address'})).map(f=>f.code);assert.deepEqual(both,['renamed-key','pattern-soft']);
 assert.deepEqual(brief(only({name:'x',mgmt:{ipv4_subnet:'172.20.20.0/24'},topology:{nodes:{}}})),[3,'warning','renamed-key','`ipv4_subnet` is an old name containerlab still accepts; the current name is `ipv4-subnet`.']);
 // Under mgmt, username is not a device setting: it stays R1 there.
 assert.equal(only({name:'x',mgmt:{username:'a'},topology:{nodes:{}}}).code,'unknown-key');
});

// ---- R2: kinds ------------------------------------------------------------------------------------------------
test('R2a: no kind resolves (error on any VM); a kind inherited through the group or the defaults counts, a kinds section cannot give one',()=>{
 const doc={name:'x',topology:{nodes:{vrt:{image:'i'}}}};
 assert.deepEqual(brief(only(doc,LOOSE)),[4,'error','kind-missing','`vrt` has no kind. Add `kind:` to the device (or to topology.defaults).']);
 assert.deepEqual(check({name:'x',topology:{defaults:{kind:'linux'},nodes:{vrt:{image:'i'}}}}),[]);
 assert.deepEqual(check({name:'x',topology:{groups:{g:{kind:'linux'}},nodes:{vrt:{image:'i',group:'g'}}}}),[]);
 assert.equal(check({name:'x',topology:{kinds:{linux:{image:'i'}},nodes:{vrt:{image:'i'}}}}).filter(f=>f.code==='kind-missing').length,1);
 assert.deepEqual(check({name:'x',topology:{nodes:{vrt:{image:'i',kind:null}}}}).map(f=>f.code),['kind-missing']);
});
test('R2b: an unknown kind with a suggestion, error when exact, warning otherwise, reported where the kind is written',()=>{
 const doc=lab({kind:'juniper_vjunos_switch'});
 assert.deepEqual(brief(only(doc)),[5,'error','kind-unknown','containerlab 0.79.0 knows no kind `juniper_vjunos_switch`. Did you mean `juniper_vjunosswitch`?']);
 assert.equal(only(doc,LOOSE).severity,'warning');
 assert.deepEqual(brief(only(lab({kind:'nosuchkind'}))),[5,'error','kind-unknown','containerlab 0.79.0 knows no kind `nosuchkind`.']);
 // From the defaults: one finding on the defaults line, however many devices inherit it.
 const many=check({name:'x',topology:{defaults:{kind:'arista_ceoss',image:'i'},nodes:{a:{},b:{},c:{}}}});
 assert.deepEqual(many.map(brief),[[4,'error','kind-unknown','containerlab 0.79.0 knows no kind `arista_ceoss`. Did you mean `arista_ceos`?']]);
 assert.deepEqual(brief(only(lab({kind:{a:1}}))),[5,'error','type','`kind` must be a kind name, not a mapping.']);
});
test('R2c: the eight short names and every vr-* name are accepted with one warning per name, worded as short or old',()=>{
 const said={ceos:'`ceos` is a short name for `arista_ceos`; the long name is what the manager’s device catalog uses.',cjunosevolved:'`cjunosevolved` is a short name for `juniper_cjunosevolved`; the long name is what the manager’s device catalog uses.'};
 for(const alias of ['ceos','srl','xrd','cvx','cumulus_cvx','crpd','cjunosevolved','c8000']){
  const f=only(lab({kind:alias}));assert.equal(f.code,'kind-alias',alias);assert.equal(f.severity,'warning');assert.equal(f.line,5);
  assert.equal(f.message,said[alias]||'`'+alias+'` is a short name containerlab accepts.');
 }
 assert.deepEqual(brief(only(lab({kind:'vr-xrv9k'}))),[5,'warning','kind-alias','`vr-xrv9k` is an old name containerlab still accepts; the current name is `cisco_xrv9k`.']);
 assert.equal(only(lab({kind:'vr-vjunosswitch'})).message,'`vr-vjunosswitch` is an old name containerlab still accepts; the current name is `juniper_vjunosswitch`.');
 assert.equal(only(lab({kind:'vr-sros'})).message,'`vr-sros` is an old name containerlab still accepts.');
 // Once per lab and name: the first device that uses it.
 const two=check(lab({kind:'ceos'},{b:{kind:'ceos',image:'i'},c:{kind:'srl',image:'i'}}));
 assert.deepEqual(two.map(f=>[f.line,f.code]),[[5,'kind-alias'],[11,'kind-alias']]);
 // A kinds section under the short name is not an unknown kind.
 assert.deepEqual(check(lab({kind:'ceos'},{},{kinds:{ceos:{image:'x'}}})).map(f=>f.code),['kind-alias']);
});

// ---- R3: images ---------------------------------------------------------------------------------------------------
test('R3: a device with no image resolves a warning; bridge and the other image-free kinds do not; inheritance counts',()=>{
 assert.deepEqual(brief(only({name:'x',topology:{nodes:{vsw:{kind:'juniper_vjunosswitch'}}}},EXACT)),[4,'warning','image-missing','`vsw` has no image. containerlab needs one to create the container; the deploy fails without it.']);
 for(const kind of ['bridge','ovs-bridge','host','ext-container'])assert.deepEqual(check({name:'x',topology:{nodes:{br:{kind}}}}),[],kind);
 assert.deepEqual(check({name:'x',topology:{kinds:{juniper_vjunosswitch:{image:'i'}},nodes:{vsw:{kind:'juniper_vjunosswitch'}}}}),[]);
 assert.deepEqual(check({name:'x',topology:{defaults:{image:'i'},nodes:{vsw:{kind:'juniper_vjunosswitch'}}}}),[]);
 assert.deepEqual(check({name:'x',topology:{groups:{g:{image:'i'}},nodes:{vsw:{kind:'juniper_vjunosswitch',group:'g'}}}}),[]);
 assert.equal(only({name:'x',topology:{nodes:{vsw:{kind:'juniper_vjunosswitch',image:''}}}}).code,'image-missing','an empty image is no image');
});

// ---- R4 and R4b: enums and stages -----------------------------------------------------------------------------
test('R4: the enums §3 names are errors when exact, the other enums warnings; the values are listed',()=>{
 assert.deepEqual(brief(only(lab({'restart-policy':'sometimes'}))),[7,'error','enum','`sometimes` is not a value containerlab 0.79.0 accepts for `restart-policy`. The values are no, on-failure, always and unless-stopped.']);
 assert.equal(only(lab({'restart-policy':'sometimes'}),LOOSE).severity,'warning');
 assert.deepEqual(brief(only(lab({'image-pull-policy':'ifnotpresnt'}))),[7,'error','enum','`ifnotpresnt` is not a value containerlab 0.79.0 accepts for `image-pull-policy`. The values are always, never and ifnotpresent. Did you mean `ifnotpresent`?']);
 assert.deepEqual(brief(only(lab({runtime:'containerd'}))),[7,'error','enum','`containerd` is not a value containerlab 0.79.0 accepts for `runtime`. The values are docker and podman.']);
 assert.deepEqual(brief(only(lab({'cgroupns-mode':'shared'}))),[7,'warning','enum','`shared` is not a value containerlab 0.79.0 accepts for `cgroupns-mode`. The values are host and private.']);
 assert.equal(only(lab({'link-apply-mode':'now'})).severity,'warning');
 for(const ok of ['Always','IfNotPresent','never'])assert.deepEqual(check(lab({'image-pull-policy':ok})),[],ok);
});
test('R4: the kind-specific type enums are warnings with a suggestion; the SR OS type pattern is tested only behind its guard (it backtracks without bound)',()=>{
 assert.deepEqual(brief(only(lab({kind:'nokia_srlinux',type:'ixrd9'}))),[7,'warning','enum','`ixrd9` is not a type containerlab 0.79.0 knows for the kind `nokia_srlinux`. Did you mean `ixrd1`?']);
 assert.deepEqual(check(lab({kind:'nokia_srlinux',type:'ixr-d3l'})),[]);
 assert.equal(only(lab({kind:'cisco_iol',type:'l3'})).message,'`l3` is not a type containerlab 0.79.0 knows for the kind `cisco_iol`. Did you mean `l2`?');
 assert.equal(only(lab({kind:'nokia_srsim',type:'sr-99'})).code,'enum');
 // The kind may come from the defaults: the condition uses the device's resolved kind.
 assert.equal(check({name:'x',topology:{defaults:{kind:'nokia_srlinux',image:'i'},nodes:{a:{type:'ixrd9'}}}}).filter(f=>f.code==='enum').length,1);
 // SR OS: an enum value and a valid custom type line pass; a value that is neither gets the enum warning (the pattern branch is tested behind its guard).
 for(const type of ['sr-1','cp: cpu=2 ram=4 ___ lc: cpu=2 ram=4'])assert.deepEqual(check(lab({kind:'nokia_sros',type})),[],type);
 for(const type of ['not a type','card=x foo'])assert.deepEqual(brief(only(lab({kind:'nokia_sros',type}))),[7,'warning','enum','`'+type+'` is not a type containerlab 0.79.0 knows for the kind `nokia_sros`.'],type);
 // Not a nokia kind: type is any text.
 assert.deepEqual(check(lab({type:'whatever'})),[]);
});
test('R4: the stage names; `boot` is reported by R4 alone (error when exact), the five stages pass',()=>{
 for(const stage of ['create','create-links','configure','healthy','exit'])assert.deepEqual(check(lab({stages:{[stage]:{exec:[{command:'ls'}]}}})),[],stage);
 assert.deepEqual(brief(only(lab({stages:{boot:{}}}))),[8,'error','enum','`boot` is not a stage. The stages are create, create-links, configure, healthy and exit.']);
 assert.equal(only(lab({stages:{boot:{}}}),LOOSE).severity,'warning');
 assert.equal(only(lab({stages:{heathy:{}}})).message,'`heathy` is not a stage. The stages are create, create-links, configure, healthy and exit. Did you mean `healthy`?');
});
test('R4b: a wait-for stage outside the five, or none, is a warning that says the wait may never end',()=>{
 const others={b:{kind:'linux',image:'alpine'}};
 assert.deepEqual(brief(only(lab({stages:{create:{'wait-for':[{node:'b',stage:'ready'}]}}},others))),[11,'warning','wait-stage','`ready` is not a stage, so this wait may never end. Use create, create-links, configure, healthy or exit.']);
 assert.deepEqual(brief(only(lab({stages:{create:{'wait-for':[{node:'b'}]}}},others))),[10,'warning','wait-stage','this wait-for entry has no `stage:`.']);
});

// ---- R5: types ------------------------------------------------------------------------------------------------------
test('R5: a collection against a scalar and text where a number belongs are errors; scalar against scalar a warning',()=>{
 assert.deepEqual(brief(only(lab({env:['A=1']}))),[7,'error','type','`env` must be a mapping of NAME: value, not a list.']);
 assert.deepEqual(brief(only(lab({image:{name:'x'}}))),[6,'error','type','`image` must be text, not a mapping.']);
 assert.deepEqual(brief(only(lab({ports:{a:1}}))),[7,'error','type','`ports` must be a list, not a mapping.']);
 assert.deepEqual(brief(only(lab({cpu:'2'}))),[7,'error','type','`cpu` must be a number, not the text `2`; write it without quotes.']);
 assert.deepEqual(brief(only(lab({cpu:'two'}))),[7,'error','type','`cpu` must be a number, not the text `two`.']);
 assert.deepEqual(brief(only({name:'x',prefix:2024,topology:{nodes:{}}})),[2,'warning','type','`prefix` is read as the text `2024`; quote it if that is meant.']);
 assert.deepEqual(brief(only(lab({image:5}))),[6,'warning','type','`image` is read as the text `5`; quote it if that is meant.']);
 assert.deepEqual(brief(only(lab({'startup-delay':1.5}))),[7,'warning','type','`startup-delay` must be a whole number, not `1.5`.']);
 assert.deepEqual(brief(only(lab({'env-files':[{a:1}]}))),[8,'error','type','item 1 of `env-files` must be text, not a mapping.']);
 assert.deepEqual(brief(only(lab({env:{A:{b:1}}}))),[8,'error','type','`A` must be text, not a mapping.']);
 assert.deepEqual(check(lab({env:{A:1,B:true,C:'x'},cpu:1.5,memory:'1Gb',labels:{a:'b'}})),[]);
 // An empty value is no value (YAML `key:`).
 assert.deepEqual(check(lab({cpu:null,env:null,binds:null})),[]);
 // Rule-owned shapes report their own type errors once.
 assert.deepEqual(brief(only(lab({stages:['create']}))),[7,'error','type','`stages` must be a mapping of stage names, not a list.']);
 assert.deepEqual(brief(only(lab({stages:{create:{'wait-for':{node:'a'}}}}))),[9,'error','type','`wait-for` must be a list of `- node: …` entries, not a mapping.']);
 assert.deepEqual(brief(only(lab({},{b:{kind:'linux',image:'i',stages:{create:{'wait-for':['a']}}}}))),[13,'error','type','each wait-for entry is a mapping with `node:` and `stage:`; `a` on its own is not one.']);
 assert.deepEqual(brief(only(lab({},{b:['x']}))),[7,'error','type','the device `b` must be a mapping of settings, not a list.']);
});

// ---- R6: patterns -----------------------------------------------------------------------------------------------------
test('R6a: the lab name, the prefix, a device name and a port mapping are errors on any VM',()=>{
 assert.deepEqual(brief(only(Object.assign(lab({}),{name:'my lab'}),LOOSE)),[1,'error','pattern-hard','the lab name `my lab` can only use letters, digits, dot, dash and underscore.']);
 assert.equal(only(Object.assign(lab({}),{name:'_lab'})).message,'the lab name `_lab` must start with a letter or digit.');
 assert.deepEqual(brief(only({name:'x',prefix:'a b',topology:{nodes:{}}})),[2,'error','pattern-hard','the prefix `a b` can only use letters, digits, dot, dash and underscore (or be empty, or __lab-name).']);
 for(const prefix of ['','__lab-name','clab'])assert.deepEqual(check({name:'x',prefix,topology:{nodes:{}}}),[],prefix);
 assert.deepEqual(brief(only(lab({},{'c d':{kind:'bridge'}}))),[7,'error','pattern-hard','the device name `c d` can only use letters, digits, dot, dash and underscore.']);
 assert.equal(only(lab({},{'c|d':{kind:'bridge'}})).message,'the device name `c|d` can only use letters, digits, dot, dash and underscore.','the schema allows |, the manager does not');
 assert.equal(only(lab({},{'_c':{kind:'bridge'}})).message,'the device name `_c` must start with a letter or digit.','the manager allows a leading _, the schema does not');
 assert.deepEqual(check(lab({},{'leaf-1.a_b':{kind:'bridge'}})),[]);
 assert.deepEqual(check(lab({ports:['8080:80','127.0.0.1:2201:22/tcp','80','5000-5002:5000/udp']})),[]);
 assert.deepEqual(brief(only(lab({ports:['8080:80','abc']}))),[9,'error','pattern-hard','`abc` is not a port mapping (host:container, e.g. 8080:80).']);
 assert.equal(only(lab({ports:['1:111111']})).code,'pattern-hard','six digits are never a port, although the schema pattern repeats its port group');
});
test('R6b: the soft patterns are warnings with a sentence per key',()=>{
 assert.deepEqual(brief(only(lab({'network-mode':'bogus'}))),[7,'warning','pattern-soft','`bogus` is not a network mode containerlab documents (host, none, container:<name>); Docker refuses it when the lab is deployed.']);
 assert.deepEqual(brief(only(lab({'mgmt-ipv4':'172.20.20.300'}))),[7,'warning','pattern-soft','`172.20.20.300` is not an IPv4 address.']);
 assert.deepEqual(brief(only(lab({'shm-size':'lots'}))),[7,'warning','pattern-soft','`lots` is not a size (for example 512mb or 1gb).']);
 assert.deepEqual(brief(only({name:'x',mgmt:{'ipv4-subnet':'172.20.20.0'},topology:{nodes:{}}})),[3,'warning','pattern-soft','`172.20.20.0` is not an IPv4 subnet (for example 172.20.20.0/24) or auto.']);
 assert.equal(only(lab({},{},{links:[{type:'host',endpoint:{node:'a',interface:'e1',mac:'zz'},'host-interface':'h'}]})).message,'`zz` is not a MAC address (for example 02:00:00:00:00:01).');
 assert.equal(only(lab({},{b:{kind:'linux',image:'i'}},{links:[{endpoints:['a:e1','b:e1'],ipv4:['10.0.0.1']}]})).message,'`10.0.0.1` is not an IPv4 address with a prefix length (for example 192.168.0.1/24).');
 for(const mode of ['host','none','container:other'])assert.deepEqual(check(lab({'network-mode':mode})),[],mode);
 assert.deepEqual(check(lab({'mgmt-ipv4':'172.20.20.5','mgmt-ipv6':'3fff:172:20:20::5','shm-size':'1gb'})),[]);
});
test('R6c: a bind is host-path:container-path; a number is an error, text without a colon a warning',()=>{
 assert.deepEqual(brief(only(lab({binds:[1]}))),[8,'error','binds','a bind is `host-path:container-path[:ro]`; `1` is not one.']);
 assert.deepEqual(brief(only(lab({binds:['data']}))),[8,'warning','binds','a bind is `host-path:container-path[:ro]`; `data` is not one.']);
 assert.deepEqual(check(lab({binds:['/a:/b','/c:/d:ro']})),[]);
 assert.deepEqual(brief(only(lab({binds:['/a:/b','/a:/b']}))),[9,'warning','unique','`binds` lists the same entry twice.']);
});
test('the generic limits are warnings with the limit in the sentence',()=>{
 assert.deepEqual(brief(only(lab({binds:[]}))),[7,'warning','limit','`binds` needs at least 1 item.']);
 assert.deepEqual(brief(only(lab({hostname:''}))),[7,'warning','limit','`hostname` must not be empty.']);
 assert.deepEqual(brief(only(lab({cpu:-1}))),[7,'warning','limit','`cpu` must be at least 0.']);
 assert.deepEqual(brief(only({name:'x',mgmt:{},topology:{nodes:{}}})),[2,'warning','limit','`mgmt` is empty; give it a setting or remove it.']);
 assert.deepEqual(brief(only({topology:{nodes:{}}})),[1,'warning','required','The file has no `name:`; containerlab needs it.']);
});

// ---- R7: links -----------------------------------------------------------------------------------------------------
const two={b:{kind:'linux',image:'alpine'}};
test('R7a: a brief link needs exactly two device:interface endpoints that differ',()=>{
 const sentence='a link needs exactly two endpoints as `device:interface`.';
 assert.deepEqual(brief(only(lab({},two,{links:[{endpoints:['a:e1']}]}))),[11,'error','link-brief',sentence]);
 assert.deepEqual(check(lab({},two,{links:[{endpoints:['a:e1','b:e1']}]})),[]);
 assert.deepEqual(brief(only(lab({},two,{links:[{endpoints:['a:e1','b:e1','b:e2']}]}))),[11,'error','link-brief',sentence]);
 assert.deepEqual(brief(only(lab({},two,{links:[{endpoints:['a','b:e1']}]}))),[11,'error','link-brief',sentence]);
 assert.deepEqual(brief(only(lab({},two,{links:[{mtu:1500}]}))),[11,'error','link-brief',sentence]);
 assert.deepEqual(brief(only(lab({},two,{links:['a:e1']}))),[11,'error','link-brief',sentence]);
 assert.deepEqual(check(lab({},two,{links:[{endpoints:['a:e1','a:e1']}]})).map(brief),[[11,'error','link-brief','both endpoints of this link are `a:e1`; a link connects two different interfaces.']],'not a duplicate of itself as well');
});
test('R7b: every long link form names its required keys; an unknown type has a suggestion; error when exact',()=>{
 const need={veth:'`endpoints`','veth-stitch':'`endpoints`','mgmt-net':'`endpoint` and `host-interface`',host:'`endpoint` and `host-interface`',macvlan:'`endpoint` and `host-interface`',
  vxlan:'`endpoint`, `remote`, `vni` and `dst-port`','vxlan-stitch':'`endpoint`, `remote`, `vni` and `dst-port`',dummy:'`endpoint`'};
 for(const [type,keys] of Object.entries(need)){
  const f=only(lab({},two,{links:[{type}]}));assert.deepEqual(brief(f),[11,'error','link-type','a `'+type+'` link needs '+keys+'.'],type);
  assert.equal(only(lab({},two,{links:[{type}]}),LOOSE).severity,'warning');
 }
 assert.deepEqual(brief(only(lab({},two,{links:[{type:'hots',endpoint:{node:'a',interface:'e1'}}]}))),[11,'error','link-type','`hots` is not a link type. The types are veth, veth-stitch, mgmt-net, host, macvlan, vxlan, vxlan-stitch and dummy. Did you mean `host`?']);
 assert.deepEqual(brief(only(lab({},two,{links:[{type:'veth',endpoints:[{node:'a',interface:'e1'}]}]}))),[12,'error','link-type','a `veth` link needs exactly two endpoints, each with `node:` and `interface:`.']);
 assert.deepEqual(brief(only(lab({},two,{links:[{type:'host',endpoint:{node:'a'},'host-interface':'h'}]}))),[12,'error','link-type','the endpoint of a `host` link is a mapping with `node:` and `interface:`.']);
 // Every form complete: no finding.
 const ep=(node,i)=>({node,interface:'e'+i});
 assert.deepEqual(check(lab({},two,{links:[{type:'veth',endpoints:[ep('a',1),ep('b',1)],mtu:9000},{type:'host',endpoint:ep('a',2),'host-interface':'h1'},{type:'mgmt-net',endpoint:ep('a',3),'host-interface':'h2'},
  {type:'macvlan',endpoint:ep('a',4),'host-interface':'eno1',mode:'bridge'},{type:'vxlan',endpoint:ep('a',5),remote:'10.0.0.2',vni:100,'dst-port':4789},{type:'dummy',endpoint:ep('b',2)}]})),[]);
 assert.equal(only(lab({},two,{links:[{type:'vxlan',endpoint:ep('a',5),remote:'10.0.0.2',vni:0,'dst-port':4789}]})).message,'`vni` must be at least 1.');
});
test('R7c: an endpoint that names no device is an error; host:, mgmt-net: and the other special endpoints pass',()=>{
 assert.deepEqual(brief(only(lab({},two,{links:[{endpoints:['a:e1','zz:e1']}]}),LOOSE)),[13,'error','link-node','the link endpoint `zz` is not a device in topology.nodes.']);
 for(const special of ['host:eth1','mgmt-net:x','macvlan:eno1'])assert.deepEqual(check(lab({},two,{links:[{endpoints:['a:e1',special]}]})),[],special);
 // containerlab validate 0.79.0: these names are not special endpoints; "Unable to find node ..." unless a node carries the name.
 for(const name of ['bridge','vxlan','vxlan-stitch','dummy'])assert.deepEqual(brief(only(lab({},two,{links:[{endpoints:['a:e1',name+':br0']}]}),LOOSE)),[13,'error','link-node','the link endpoint `'+name+'` is not a device in topology.nodes.'],name);
 assert.deepEqual(check(lab({},{...two,bridge:{kind:'bridge'}},{links:[{endpoints:['a:e1','bridge:br0']}]})),[],'a listed bridge node is a device');
 assert.deepEqual(brief(only(lab({},two,{links:[{type:'host',endpoint:{node:'zz',interface:'e1'},'host-interface':'h'}]}))),[13,'error','link-node','the link endpoint `zz` is not a device in topology.nodes.']);
});
test('R7d: the same device:interface twice is a warning naming the first link',()=>{
 assert.deepEqual(check(lab({},two,{links:[{endpoints:['a:e1','b:e1']},{endpoints:['a:e1','b:e2']}]})).map(brief),[[15,'warning','link-duplicate','`a:e1` is already used by the link on line 11.']]);
});

// ---- R8: the boot order graph --------------------------------------------------------------------------------------
const waitFor=(node,stage='create',on='create')=>({stages:{[on]:{'wait-for':[{node,stage}]}}});
test('R8a: a wait for a device that does not exist (with a suggestion), on any VM',()=>{
 const doc=JSON.parse(JSON.stringify(EXAMPLE));doc.topology.nodes.vrt.stages.create['wait-for'][0].node='vws';
 assert.deepEqual(check(doc,LOOSE).map(brief),[[13,'error','wait-node','There is no device named `vws`. Did you mean `vsw`?']]);
 assert.deepEqual(check(doc,EXACT,null).map(brief),[[13,'error','wait-node','There is no device named `vws`. Did you mean `vsw`?']]);
 assert.deepEqual(brief(only(lab({stages:{create:{'wait-for':[{stage:'create'}]}}}))),[10,'warning','wait-node','this wait-for entry names no device (`node:`), so it waits for nothing.']);
});
test('R8b: a device waiting for itself, directly or through the defaults, a kind section or a group',()=>{
 assert.deepEqual(brief(only(lab(waitFor('a')))),[10,'error','wait-self','A device cannot wait for itself (`a` waits for `a`).']);
 const viaDefaults=check({name:'x',topology:{defaults:Object.assign({kind:'linux',image:'i'},waitFor('a')),nodes:{a:{},b:{}}}});
 assert.deepEqual(viaDefaults.map(brief),[[9,'error','wait-self','A device cannot wait for itself (`a` waits for `a` through topology.defaults).']]);
 assert.equal(check({name:'x',topology:{kinds:{linux:waitFor('a')},nodes:{a:{kind:'linux',image:'i'}}}})[0].message,'A device cannot wait for itself (`a` waits for `a` through topology.kinds.linux).');
 assert.equal(check({name:'x',topology:{groups:{g:waitFor('a')},nodes:{a:{kind:'linux',image:'i',group:'g'}}}})[0].message,'A device cannot wait for itself (`a` waits for `a` through topology.groups.g).');
});
test('R8c: a loop of two, a loop of three reported once at its first entry, a chain is no loop, whatever the stages',()=>{
 const n=(wait)=>Object.assign({kind:'linux',image:'i'},wait);
 assert.deepEqual(check({name:'x',topology:{nodes:{vsw:n(waitFor('vrt')),vrt:n(waitFor('vsw','configure','healthy'))}}}).map(brief),
  [[10,'error','wait-loop','Devices wait for each other in a loop (vsw → vrt → vsw). containerlab will not deploy the lab.']]);
 const three=check({name:'x',topology:{nodes:{a:n(waitFor('b')),b:n(waitFor('c')),c:n(waitFor('a'))}}},LOOSE,null);
 assert.deepEqual(three.map(brief),[[10,'error','wait-loop','Devices wait for each other in a loop (a → b → c → a). containerlab will not deploy the lab.']]);
 assert.deepEqual(check({name:'x',topology:{nodes:{a:n(waitFor('b')),b:n(waitFor('c')),c:n({})}}}),[]);
 // Two separate loops: two findings.
 assert.equal(check({name:'x',topology:{nodes:{a:n(waitFor('b')),b:n(waitFor('a')),c:n(waitFor('d')),d:n(waitFor('c'))}}}).filter(f=>f.code==='wait-loop').length,2);
 // A loop made through the defaults: every device waits for a, and a waits for b.
 const viaDefaults=check({name:'x',topology:{defaults:Object.assign({kind:'linux',image:'i'},waitFor('a')),nodes:{a:waitFor('b','create','configure'),b:{}}}}).filter(f=>f.code==='wait-loop');
 assert.deepEqual(viaDefaults.map(f=>f.message),['Devices wait for each other in a loop (b → a → b). containerlab will not deploy the lab.']);
});
test('R8d: waiting for healthy on a device with no health check, own or inherited; the linux wording',()=>{
 const doc=(target,extra={})=>({name:'x',topology:Object.assign({nodes:{c1:Object.assign({kind:'arista_ceos',image:'ceos'},target),r1:Object.assign({kind:'linux',image:'i'},waitFor('c1','healthy'))}},extra)});
 assert.deepEqual(check(doc({})).map(brief),[[14,'warning','wait-health','`c1` has no health check, so it never reports healthy and this wait never ends. Wait for `create-links` or `configure` instead, or give `c1` a `healthcheck:`.']]);
 assert.deepEqual(check(doc({healthcheck:{test:['CMD','true']}})),[]);
 assert.deepEqual(check(doc({},{kinds:{arista_ceos:{healthcheck:{test:['CMD','true']}}}})),[]);
 assert.deepEqual(check({name:'x',topology:{nodes:{h1:{kind:'linux',image:'alpine'},r1:Object.assign({kind:'linux',image:'i'},waitFor('h1','healthy'))}}}).map(f=>f.message),
  ['`h1` shows healthy only if its image defines a health check or the device has a `healthcheck:`; otherwise this wait never ends.']);
 assert.deepEqual(check(doc({kind:'juniper_vjunosswitch'})),[],'vrnetlab kinds define a health check');
});

// ---- R9: stage commands and wait-for entries --------------------------------------------------------------------------
test('R9a/R9b: the binary reads stage commands as a list of mappings; an entry without phase has no finding',()=>{
 assert.deepEqual(brief(only(lab({stages:{create:{exec:{'on-enter':['ls']}}}}),LOOSE)),[9,'error','exec-form','containerlab 0.79.0 reads stage commands as a list of `- command: …` entries (with `phase: on-enter` or `on-exit` and `target: container` or `host`), not as on-enter/on-exit sections.']);
 assert.deepEqual(brief(only(lab({stages:{create:{exec:['ls -l']}}}))),[10,'error','exec-entry','each stage command is a mapping with `command:`; `ls -l` on its own is not one.']);
 assert.deepEqual(brief(only(lab({stages:{create:{exec:'ls'}}}))),[9,'error','exec-form','stage commands are a list of `- command: …` entries; `ls` on its own is not one.']);
 assert.deepEqual(check(lab({stages:{create:{exec:[{command:'ls'}]}}})),[],'no phase: containerlab defaults it to on-enter');
 assert.deepEqual(check(lab({stages:{create:{exec:[{command:'ls',phase:'on-exit',target:'host'}]}}})),[]);
 assert.deepEqual(brief(only(lab({stages:{create:{exec:[{command:'ls',phase:'later'}]}}}))),[11,'warning','exec-entry','`later` is not a phase. Use on-enter or on-exit.']);
 assert.deepEqual(brief(only(lab({stages:{create:{exec:[{command:'ls',target:'vm'}]}}}))),[11,'warning','exec-entry','`vm` is not a target. Use container or host.']);
 assert.deepEqual(brief(only(lab({stages:{create:{exec:[{phase:'on-enter'}]}}}))),[10,'error','exec-entry','each stage command is a mapping with `command:`; this one has none.']);
});
test('R9c: a wait-for entry has node and stage only (`until` is the upstream UI word), error when exact',()=>{
 const doc=lab({stages:{create:{'wait-for':[{node:'b',stage:'create',until:'healthy'}]}}},two);
 assert.deepEqual(brief(only(doc)),[12,'error','wait-extra','a wait-for entry has `node` and `stage` only; `until` is not a setting.']);
 assert.equal(only(doc,LOOSE).severity,'warning');
});

// ---- rule-owned paths: exactly one finding, from the named rule ---------------------------------------------------------
test('rule-owned paths: kind, the keys of stages, a wait-for stage, an exec entry and a link each yield exactly one finding',()=>{
 const cases=[
  [lab({kind:'nosuch'}),'kind-unknown','error'],
  [lab({stages:{create:{'wait-for':[{node:'b',stage:'ready'}]}}},two),'wait-stage','warning'],
  [lab({stages:{boot:{exec:[{command:'ls'}]}}}),'enum','error'],
  [lab({stages:{create:{exec:[{command:'ls',phase:'later'}]}}}),'exec-entry','warning'],
  [lab({stages:{create:{exec:[{target:'host'}]}}}),'exec-entry','error'],
  [lab({},two,{links:[{type:'host',endpoint:{node:'a',interface:'e1'}}]}),'link-type','error'],
  [lab({kind:'ceos'}),'kind-alias','warning'],
 ];
 for(const [doc,code,severity] of cases){const list=check(doc);assert.equal(list.length,1,code+': '+JSON.stringify(list));assert.equal(list[0].code,code);assert.equal(list[0].severity,severity);}
});

// ---- without the schema --------------------------------------------------------------------------------------------------
test('schema === null runs the schema-free rules only (R0, R2a, R3, R7a/c/d, R8a–d, R9a/b)',()=>{
 const doc={name:'my lab',foo:1,topology:{nodes:{a:{imge:'x',env:['A=1'],kind:'nosuch',stages:{boot:{},create:{exec:{'on-enter':['ls']},'wait-for':[{node:'zz',stage:'ready',until:1}]}}},b:{kind:'juniper_vjunosswitch'},
  c:Object.assign({kind:'linux',image:'i'},waitFor('c'))},links:[{endpoints:['a:e1']},{endpoints:['a:e2','zz:e1']},{type:'hots'}]}};
 const free=plain(C.builderCheck(located(doc),null,EXACT)),codes=new Set(free.map(f=>f.code));
 assert.deepEqual([...codes].sort(),['exec-form','image-missing','link-brief','link-node','wait-node','wait-self']);
 const allowed=['shape','kind-missing','image-missing','link-brief','link-node','link-duplicate','wait-node','wait-self','wait-loop','wait-health','exec-form','exec-entry'];
 for(const f of free)assert.ok(allowed.includes(f.code),f.code);
 const full=new Set(check(doc).map(f=>f.code));
 for(const code of ['unknown-key','type','kind-unknown','enum','wait-stage','wait-extra','pattern-hard','link-type'])assert.ok(full.has(code),code);
 assert.deepEqual(plain(C.builderCheck(located({name:'x',topology:{nodes:{a:{}}}}),null,{})).map(f=>f.code),['kind-missing','image-missing']);
});

// ---- the list: order, cap, summary --------------------------------------------------------------------------------------------
test('the list is sorted by line with errors first on a line, and a finding of an inherited entry appears once',()=>{
 const list=check(lab({},{},{defaults:{stages:{create:{'wait-for':[{node:'zz',stage:'ready'}]}}}}));
 assert.deepEqual(list.map(f=>[f.line,f.severity,f.code]),[[11,'error','wait-node'],[12,'warning','wait-stage']]);
 const many=check(lab({imge:'x',username:'u'}));for(let i=1;i<many.length;i++)assert.ok(many[i-1].line<=many[i].line);
 const sameLine=plain(C.builderCheck({kind:'map',line:1,items:[{key:'name',keyLine:1,value:{kind:'scalar',line:1,value:'my lab',tag:'str'}},{key:'prefix',keyLine:1,value:{kind:'scalar',line:1,value:2024,tag:'int'}},{key:'topology',keyLine:1,value:{kind:'map',line:1,items:[]}}]},SCHEMA,EXACT));
 assert.deepEqual(sameLine.map(f=>f.severity),['error','warning'],'a flow mapping on one line: errors first');
});
test('the list stops at 200 items with one closing item, and the summary still counts every finding',()=>{
 const nodes={};for(let i=0;i<150;i++)nodes['n'+i]={kind:'nosuch'};
 const list=check({name:'x',topology:{nodes}});
 assert.equal(list.length,201);const last=list[200];
 assert.equal(last.code,'more');assert.equal(last.message,'… and 100 more.');assert.equal(last.line,0);
 assert.deepEqual(plain(C.builderCheckSummary(list)),{errors:150,warnings:150,text:'150 errors, 150 warnings'});
});
test('the summary sentence: no problems, one warning, one error, two of each',()=>{
 assert.deepEqual(plain(C.builderCheckSummary([])),{errors:0,warnings:0,text:'No problems found'});
 assert.deepEqual(plain(C.builderCheckSummary(undefined)),{errors:0,warnings:0,text:'No problems found'});
 assert.equal(C.builderCheckSummary([{severity:'warning'}]).text,'1 warning');
 assert.equal(C.builderCheckSummary([{severity:'error'}]).text,'1 error');
 assert.equal(C.builderCheckSummary([{severity:'error'},{severity:'warning'},{severity:'error'}]).text,'2 errors, 1 warning');
 assert.equal(C.builderCheckSummary([{severity:'error'},{severity:'warning'},{severity:'error'},{severity:'warning'}]).text,'2 errors, 2 warnings');
});
test('every finding has the contract shape, and no sentence carries a JSON pointer or a Go type name',()=>{
 const doc={name:'my lab',foo:1,mgmt:{bogus:1},topology:{defaults:{imge:1},nodes:{a:{imge:'x',env:['A=1'],kind:'nosuch',ports:['abc'],binds:[1],stages:{boot:{},create:{exec:{'on-enter':['ls']},'wait-for':[{node:'zz',stage:'ready',until:1}]}}},b:{kind:'ceos'}},links:[{endpoints:['a:e1']},{type:'hots'}]}};
 const list=check(doc);assert.ok(list.length>=15,list.length);
 for(const f of list){
  assert.deepEqual(Object.keys(f).sort(),['code','line','message','path','severity']);
  assert.ok(f.severity==='error'||f.severity==='warning');assert.ok(Number.isInteger(f.line)&&f.line>0);assert.match(f.code,/^[a-z-]+$/);
  assert.ok(Array.isArray(f.path)&&f.path.every(p=>typeof p==='string'));
  assert.doesNotMatch(f.message,/#\/|types\.|core\.Config|definitions|\bundefined\b|\[object|NaN/,f.message);assert.doesNotMatch(f.message,/^Line \d/);
 }
});

// ---- which schema: §2.3 -------------------------------------------------------------------------------------------------------
test('builderSchemaChoice: every row of §2.3, never exact for a suffix or a partial version',()=>{
 const pick=(vm,list)=>{const c=plain(C.builderSchemaChoice(vm,list));return [c.schemaVersion,c.exact,c.reason,c.caption];};
 assert.deepEqual(pick('0.79.0',['0.79.0']),['0.79.0',true,'exact','Checked against containerlab 0.79.0, the version on this VM.']);
 assert.deepEqual(pick('0.81.0',['0.79.0']),['0.79.0',false,'newer','Checked against the containerlab 0.79.0 schema; this VM runs 0.81.0. A setting added since then is shown as a warning, not an error.']);
 assert.deepEqual(pick('0.79.3',['0.79.0','0.80.0']),['0.79.0',false,'between','Checked against the containerlab 0.79.0 schema; this VM runs 0.79.3.']);
 assert.deepEqual(pick('0.70.0',['0.79.0']),['0.79.0',false,'older','Checked against the containerlab 0.79.0 schema; this VM runs 0.70.0, older than any schema the manager carries. containerlab itself reports settings it does not know when the lab is deployed.']);
 assert.deepEqual(pick('0.79.0-rc1',['0.79.0']),['0.79.0',false,'between','Checked against the containerlab 0.79.0 schema; this VM runs 0.79.0-rc1.']);
 assert.deepEqual(pick('0.79.0+dev',['0.79.0']).slice(0,3),['0.79.0',false,'between']);
 assert.deepEqual(pick('0.81.0-rc1',['0.79.0']).slice(0,3),['0.79.0',false,'newer']);
 const unknown='The VM’s containerlab version is not known yet (not connected, or the VM’s manager tools are older), so the text is checked against the containerlab 0.79.0 schema; unknown settings are shown as warnings.';
 for(const vm of ['','0.79','dev',undefined,null,79])assert.deepEqual(pick(vm,['0.79.0']),['0.79.0',false,'unknown',unknown],String(vm));
 // Two vendored versions: the newest when the VM is unknown, the exact one when it matches, the greatest below otherwise.
 assert.deepEqual(pick('',['0.80.0','0.79.0']).slice(0,2),['0.80.0',false]);
 assert.deepEqual(pick('0.80.0',['0.79.0','0.80.0']).slice(0,2),['0.80.0',true]);
 assert.deepEqual(pick('0.80.9',['0.79.0','0.80.0','0.81.0']).slice(0,3),['0.80.0',false,'between']);
 // The default list is BUILDER_SCHEMA_VERSIONS; an entry that is not x.y.z never becomes a choice (it would become a URL).
 assert.deepEqual(pick('0.79.0').slice(0,2),['0.79.0',true]);
 assert.deepEqual(pick('../x',['../x','0.79.0']).slice(0,3),['0.79.0',false,'unknown']);
 assert.deepEqual(pick('0.79.0',[]).slice(0,3),['',false,'none']);
 assert.equal(C.builderSchemaChoice('0.79.0 ',['0.79.0']).exact,false,'whole-string equality');
});

// ---- key help: §4.3 --------------------------------------------------------------------------------------------------------------
test('builderKeyHelp: a device key, a nested wait-for key, a line without a key, a non-containerlab.dev link, no schema',()=>{
 const t=located(EXAMPLE);
 assert.deepEqual(plain(C.builderKeyHelp(t,SCHEMA,5)),{key:'kind',path:['topology','nodes','vsw','kind'],description:'kind of this node',url:'https://containerlab.dev/manual/nodes/#kind'});
 assert.deepEqual(plain(C.builderKeyHelp(t,SCHEMA,13)),{key:'node',path:['topology','nodes','vrt','stages','create','wait-for','0','node'],description:'node name to wait for',url:''});
 assert.deepEqual(plain(C.builderKeyHelp(t,SCHEMA,10)),{key:'stages',path:['topology','nodes','vrt','stages'],description:"node's stages configurations",url:'https://containerlab.dev/manual/nodes/#stages'});
 // The brief link's endpoints: its markdownDescription links to localhost, so there is no link.
 assert.deepEqual(plain(C.builderKeyHelp(t,SCHEMA,16)),{key:'endpoints',path:['topology','links','0','endpoints'],description:'endpoints list',url:''});
 assert.equal(C.builderKeyHelp(t,SCHEMA,17),null,'a list item line has no key');
 assert.equal(C.builderKeyHelp(t,SCHEMA,99),null);assert.equal(C.builderKeyHelp(t,null,5),null);assert.equal(C.builderKeyHelp(null,SCHEMA,5),null);assert.equal(C.builderKeyHelp(t,SCHEMA,0),null);
 const odd=located(lab({imge:'x',mgmt_ipv4:'1.2.3.4'}));
 assert.equal(C.builderKeyHelp(odd,SCHEMA,7),null,'an unknown key has no help');
 assert.equal(C.builderKeyHelp(odd,SCHEMA,8).url,'https://containerlab.dev/manual/nodes/#mgmt-ipv4','a renamed key shows the current name\'s help');
 assert.equal(C.builderKeyHelp(located(lab({'startup-config':'a.cfg'})),SCHEMA,7).description,'path to a startup config file (if supported by the kind)');
 for(const help of [C.builderKeyHelp(t,SCHEMA,5),C.builderKeyHelp(odd,SCHEMA,8)])assert.match(help.url,/^https:\/\/containerlab\.dev\//);
});

// ---- the schema's patterns ------------------------------------------------------------------------------------------------------
test('builderCheckSelfTest: every pattern of the vendored schema compiles; the two that backtrack without bound are known',()=>{
 const r=plain(C.builderCheckSelfTest(SCHEMA));
 assert.equal(r.failed,0,JSON.stringify(r.failures));assert.equal(r.patterns,33);
 assert.deepEqual(r.risky.sort(),['#/definitions/node-config/allOf/2/then/properties/type/anyOf/1/pattern','#/definitions/node-config/properties/ports/items/pattern']);
 const broken=plain(C.builderCheckSelfTest({properties:{a:{pattern:'(['},b:{pattern:'^ok$'}}}));
 assert.equal(broken.failed,1);assert.equal(broken.patterns,2);
});
test('crafted strings finish fast: the port guard, the untested SR OS pattern, the 1,024-character cap',()=>{
 const start=Date.now();
 const ports=['1-1:'+'1'.repeat(40)+'x','1:'+'1'.repeat(1000),'1.1.1.1:1:'+'1'.repeat(60)+'/x','1:1'+'1'.repeat(30)+'/x'];
 const list=check(lab({ports}));assert.equal(list.filter(f=>f.code==='pattern-hard').length,4);
 assert.deepEqual(check(lab({kind:'nokia_sros',type:'cpu=1  ___ '.repeat(90)})),[]);
 const long=check(lab({'mgmt-ipv6':'1'.repeat(1100)}));assert.deepEqual(long.map(brief),[[7,'warning','too-long','`mgmt-ipv6` is too long to check (more than 1,024 characters).']]);
 for(const n of [1,10,100])check(lab({'shm-size':'1'.repeat(n*10)+'x','network-mode':'container:'+'a'.repeat(n*10)+' ','mgmt-ipv6':':'.repeat(n*10)+'g'}));
 assert.ok(Date.now()-start<2000,'took '+(Date.now()-start)+' ms');
 // The risky test: nested unbounded repetition only.
 assert.equal(C.builderCheckRisky('^(a+)+$'),true);assert.equal(C.builderCheckRisky('^([0-9]{1,4}|x)+$'),true);
 assert.equal(C.builderCheckRisky('^(a|b){0,5}$'),false);assert.equal(C.builderCheckRisky('^[a-z]+(%[a-z]+)?$'),false);assert.equal(C.builderCheckRisky('^(?:ab)+$'),false);
});

// ---- robustness --------------------------------------------------------------------------------------------------------------------
test('a tree that nests 10,000 levels is checked without a throw; key help still finds a key deep inside',()=>{
 let deep={kind:'scalar',line:10010,value:'x',tag:'str'};
 for(let i=10000;i>0;i--)deep={kind:'map',line:10+i,items:[{key:'k',keyLine:10+i,value:deep}]};
 const tree=located(lab({config:{vars:{}}},{b:{kind:'linux',image:'i',stages:{create:{'wait-for':[{node:'a',stage:'create'},{node:'a',stage:'create'}]}}}}));
 // Put the deep value under config.vars (schema-free) and as the node of both wait-for entries.
 tree.items[1].value.items[0].value.items[0].value.items[2].value.items[0].value=deep;
 const wait=tree.items[1].value.items[0].value.items[1].value.items[2].value.items[0].value.items[0].value;
 wait.items[0].items[0].value=deep;wait.items[1].items[0].value=deep;
 const list=plain(C.builderCheck(tree,SCHEMA,EXACT));
 assert.ok(Array.isArray(list));
 assert.equal(C.builderKeyHelp(tree,SCHEMA,10005),null,'config.vars is free-form: no help, and no throw');
 assert.equal(C.builderKeyHelp(tree,SCHEMA,10).key,'kind','a key after the deep part is still found');
 assert.deepEqual(plain(C.builderCheck(tree,null,EXACT)).filter(f=>f.code==='shape'),[]);
});
test('odd trees never throw: random located values in every place (a fixed seed, 400 trees)',()=>{
 let seed=20261023;const rnd=n=>{seed=(seed*1103515245+12345)%2147483648;return seed%n;};
 const keys=['name','topology','nodes','links','kinds','groups','defaults','kind','image','stages','create','healthy','wait-for','node','stage','exec','command','phase','endpoints','endpoint','type','env','ports','binds','a','b','mgmt','ipv4-subnet','healthcheck','group','cpu','x'];
 const scalars=[null,0,1.5,-3,true,'a','b','a:e1','b:e1','vr-xrv9k','ceos','healthy','8080:80','',' ','x'.repeat(2000)];
 const gen=d=>{const k=rnd(d>5?1:3);if(k===0)return scalars[rnd(scalars.length)];if(k===1){const o={};for(let i=rnd(5);i>0;i--)o[keys[rnd(keys.length)]]=gen(d+1);return o;}const a=[];for(let i=rnd(4);i>0;i--)a.push(gen(d+1));return a;};
 for(let i=0;i<400;i++){
  const doc={name:gen(3),topology:{nodes:{a:gen(1),b:gen(1)},links:gen(2),defaults:gen(2),kinds:gen(2),groups:gen(2)}};
  for(const schema of [SCHEMA,null])for(const ctx of [EXACT,LOOSE,undefined]){
   const list=plain(C.builderCheck(located(doc),schema,ctx));
   for(const f of list)assert.ok(f.line>=0&&typeof f.message==='string'&&f.message.length>0&&!/undefined|\[object/.test(f.message),JSON.stringify(f));
   C.builderCheckSummary(list);
  }
  C.builderKeyHelp(located(doc),SCHEMA,1+rnd(40));
 }
});

// ---- the panel fixes after the independent verification (docs/parity-campaign/C08-DESIGN.md §3, §4, §9) ----------
test('the SR OS type guard: a long or strange value is not tested and returns at once; a wrong short one warns',()=>{
 const start=Date.now();
 for(const type of ['x'.repeat(300),'cpu=1 '.repeat(10)+'!','cpu=1  ___ '.repeat(90)+'x','é'.repeat(20)])assert.deepEqual(check(lab({kind:'nokia_sros',type})),[],type.slice(0,20));
 assert.equal(check(lab({kind:'nokia_sros',type:'cpu=1 '.repeat(10)+'x'})).length,1,'a 61-character value inside the guard is tested');
 assert.equal(check(lab({kind:'nokia_sros',type:'a'.repeat(65)})).length,0,'65 characters: over the cap, untested');
 assert.ok(Date.now()-start<500,'took '+(Date.now()-start)+' ms');
});
test('a wait loop names at most eight devices and counts the rest',()=>{
 const n=12,nodes={};
 for(let i=0;i<n;i++)nodes['n'+i]={kind:'linux',image:'i',stages:{create:{'wait-for':[{node:'n'+((i+1)%n),stage:'create'}]}}};
 const f=check({name:'x',topology:{nodes}}).filter(x=>x.code==='wait-loop');
 assert.equal(f.length,1);
 assert.match(f[0].message,/^Devices wait for each other in a loop \((n\d+ → ){8}… \(5 more\)\)\. containerlab will not deploy the lab\.$/);
 const small=check({name:'x',topology:{nodes:{a:{kind:'linux',image:'i',stages:{create:{'wait-for':[{node:'b',stage:'create'}]}}},b:{kind:'linux',image:'i',stages:{create:{'wait-for':[{node:'a',stage:'create'}]}}}}}}).filter(x=>x.code==='wait-loop');
 assert.match(small[0].message,/\(a → b → a\)/);
});
test('an environment-variable prefix is an error the manager refuses, not containerlab; an ordinary bad prefix stays containerlab’s',()=>{
 const f=check({name:'x',prefix:'${CLAB_PREFIX:=""}',topology:{nodes:{}}});
 assert.equal(f.length,1);assert.equal(f[0].severity,'error');assert.equal(f[0].code,'pattern-hard');assert.equal(f[0].refuser,'manager');
 assert.match(f[0].message,/^the manager’s import refuses this prefix \(`\$\{CLAB_PREFIX:=""\}`\)/);
 const plainBad=check({name:'x',prefix:'a b',topology:{nodes:{}}});
 assert.equal(plainBad[0].refuser,undefined,'no refuser field means containerlab');
});
test('YAML merge keys: the anchor’s keys apply, the map’s own keys win, and `<<` is never an unknown key',()=>{
 const entry=(key,keyLine,value)=>({key,keyLine,value});
 const sc=(v,line)=>({kind:'scalar',line,value:v,tag:'str'});
 const anchor={kind:'map',line:4,items:[entry('kind',4,sc('linux',4)),entry('image',5,sc('alpine:3',5))]};
 const own={kind:'map',line:8,items:[entry('<<',8,anchor),entry('image',9,sc('own:1',9))]};
 const merged=C.builderCheckMerged(own,0);
 assert.deepEqual(plain(merged.items.map(i=>[i.key,i.value.value])),[['image','own:1'],['kind','linux']]);
 const tree={kind:'map',line:1,items:[entry('name',1,sc('x',1)),entry('topology',2,{kind:'map',line:3,items:[entry('nodes',3,{kind:'map',line:4,items:[entry('a',4,anchor),entry('b',8,own)]})]})]};
 const list=plain(C.builderCheck(tree,SCHEMA,EXACT));
 assert.deepEqual(list.filter(f=>f.code==='unknown-key'||f.code==='kind-missing'),[],JSON.stringify(list));
 // A list of anchors: the earlier one wins; a value that is neither a map nor a list of maps adds nothing and is not reported as a key.
 const a1={kind:'map',line:1,items:[entry('image',1,sc('one',1))]},a2={kind:'map',line:2,items:[entry('image',2,sc('two',2)),entry('kind',2,sc('linux',2))]};
 const two=C.builderCheckMerged({kind:'map',line:3,items:[entry('<<',3,{kind:'seq',line:3,items:[a1,a2]})]},0);
 assert.deepEqual(plain(two.items.map(i=>[i.key,i.value.value])),[['image','one'],['kind','linux']]);
 assert.deepEqual(plain(C.builderCheckMerged({kind:'map',line:1,items:[entry('<<',1,sc('x',1))]},0).items),[]);
 const untouched={kind:'map',line:1,items:[entry('a',1,sc('1',1))]};assert.equal(C.builderCheckMerged(untouched,0),untouched,'no `<<`: the same tree');
});
