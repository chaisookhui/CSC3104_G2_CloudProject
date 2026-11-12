const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');

function browser({offline=false,admin=false}={}) {
  const values=new Map(),elements=new Map();
  const element=id=>{if(!elements.has(id))elements.set(id,{addEventListener(){},hidden:false});return elements.get(id);};
  const owned={user_id:'server-owned',name:'Alice'};
  const state={selected:{user_id:'forged'},calls:[]};
  const context=vm.createContext({console,Map,Promise,crypto:{randomUUID:()=> 'stable-creation-nonce'},
    fetch:async()=>{if(offline)throw new Error('offline');return {ok:true,json:async()=>({enabled:true,admin,csrf:'csrf',users:[owned]})};},
    load:key=>values.get(key),save:(key,value)=>values.set(key,value),getCurrentUser:()=>state.selected,
    selectDemoIdentity:user=>{state.selected=user;},rememberDemoUser:user=>values.set('remembered',user),
    api:async(path,body)=>{state.calls.push({path,body});return owned;},
    document:{getElementById:element,querySelector:element}});
  context.window=context;
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/access.js'),'utf8'),context);
  return {context,state,element,values};
}

test('server session removes forged cached users and hides administrator controls',async()=>{
  const b=browser();await b.context.initializeAccess();
  assert.equal(b.state.selected,null);
  assert.equal(b.element('.admin-group').hidden,true);
  assert.equal(b.values.get('remembered').user_id,'server-owned');
  assert.equal(b.context.allowedBrowserUsers.has('forged'),false);
  const options={method:'POST',headers:{'Content-Type':'application/json'}};
  await b.context.prepareApi(options);
  assert.equal(options.headers['X-CSRF-Token'],'csrf');
});
test('server creates browser identities and network failure does not fall back to client ownership',async()=>{
  const b=browser();const user=await b.context.createBrowserIdentity('Alice');
  assert.equal(user.user_id,'server-owned');
  assert.equal(b.state.calls[0].body.key,'stable-creation-nonce');
  await assert.rejects(browser({offline:true}).context.createBrowserIdentity('Alice'),/offline/);
});
