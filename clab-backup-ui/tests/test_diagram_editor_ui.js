const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const context=vm.createContext({});vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/diagram-editor.js'),'utf8'),context);
test('annotations start with editable defaults and payload retains revision and node identity',()=>{
 const a=context.diagramAnnotation('text',10,20);assert.equal(a.text,'New text');assert.equal(a.x,10);
 const p=context.diagramPayload({nodes:[{id:'router',x:2,y:3}],decorations:[a],revision:'saved-revision'});
 assert.deepEqual(JSON.parse(JSON.stringify(p.positions)),{router:[2,3]});assert.equal(p.revision,'saved-revision');assert.equal(p.decorations[0],a);
});
test('moving lines moves both endpoints and clamps out-of-range coordinates',()=>{
 const a=context.diagramAnnotation('line',10,20);context.diagramMove(a,30,40);assert.equal(a.x,40);assert.equal(a.y,60);assert.equal(a.x2,240);assert.equal(a.y2,180);
 context.diagramMove(a,200000,-200000);assert.equal(a.x,100000);assert.equal(a.y,-100000);assert.ok(a.x2<=100000);assert.ok(a.y2>=-100000);
});
