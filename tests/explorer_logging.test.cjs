// Run with Node's built-in test runner; no browser packages are required.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../pipeline/explorer.js'),'utf8').split('const matchColors=')[0];

function harness(){
 const requests=[],elements=new Map(),timers=[];
 class Target{
  constructor(){this.listeners={};this.value='';this.checked=true;this.dataset={eventsEndpoint:'/runs/1/events'};this.classList={add(){}}}
  addEventListener(type,handler){(this.listeners[type]??=[]).push(handler)}
  dispatch(type,event={}){for(const handler of this.listeners[type]||[])handler({type,target:{closest:()=>null},...event})}
 }
 const get=id=>{if(!elements.has(id))elements.set(id,new Target());return elements.get(id)};
 const document=new Target(),window=new Target(),svg=new Target();document.body=new Target();
 const context=vm.createContext({document,window,svg,$:get,crypto:{randomUUID:()=> 'page-1'},
  TextEncoder,Date,Map,Set,JSON,Promise,queueMicrotask,
  setInterval:callback=>timers.push(callback),
  selected:null,focus:null,zoom:1,panX:0,panY:0,drag:null,visible:[],links:[],
  data:{run_id:'run-1'},byId:new Map([['water',{id:'water',x:10,y:20}]]),
  details(item){context.selected=item.id},
  fetch:async (url,options)=>{requests.push({url,...JSON.parse(options.body),keepalive:options.keepalive});return {ok:context.succeed}},
  succeed:true,
 });
 vm.runInContext(source,context);
 return {context,requests,get,document,window,svg,run:code=>vm.runInContext(code,context)};
}

test('opening and selecting a graph logs to its route with page identity and state',async()=>{
 const h=harness();await new Promise(setImmediate);
 assert.equal(h.requests[0].url,'/runs/1/events');
 assert.equal(h.requests[0].events[0].action,'page_open');
 h.run("details({id:'water'})");
 h.get('search').value='water';h.get('search').dispatch('input');
 await h.run('flushInteractions()');
 const events=h.requests[1].events;
 assert.deepEqual(events.map(e=>e.action),['select','search']);
 assert.equal(events[0].details.id,'water');
 assert.equal(events[1].details.text,'water');
 assert.equal(h.requests[1].page_id,'page-1');
 assert.deepEqual(events.map(e=>e.sequence),[2,3]);
});

test('failed saves retain events for retry and page hide uses keepalive',async()=>{
 const h=harness();await new Promise(setImmediate);
 h.context.succeed=false;
 h.get('query-text').value='unsubmitted question';h.get('query-text').dispatch('input');
 await h.run('flushInteractions()');
 assert.match(h.get('logging-status').textContent,/unavailable/);
 const sequence=h.requests[1].events[0].sequence;
 h.context.succeed=true;
 h.window.dispatch('pagehide',{persisted:false});await new Promise(setImmediate);
 assert.equal(h.requests[2].keepalive,true);
 assert.equal(h.requests[2].events[0].sequence,sequence);
 assert.equal(h.requests[2].events[1].action,'page_hide');
 assert.equal(h.run('interactionQueue.length'),0);
});

test('drag, pan, zoom and controls capture their resulting state',async()=>{
 const h=harness();await new Promise(setImmediate);
 const nodeElement={};h.context.visible=[{id:'water',element:nodeElement}];
 h.svg.dispatch('pointerdown',{clientX:1,clientY:1,target:{closest:selector=>selector==='.node'?nodeElement:null}});
 h.context.drag=null;
 h.svg.dispatch('pointerup',{clientX:10,clientY:20});
 h.context.drag={};h.svg.dispatch('pointerdown',{clientX:1,clientY:1});await new Promise(setImmediate);
 h.context.panX=100;h.context.drag=null;h.svg.dispatch('pointerup',{clientX:101,clientY:1});
 h.context.zoom=2;h.svg.dispatch('wheel',{deltaY:20});
 for(const id of ['focus','reset','fit'])h.get(id).dispatch('click');
 for(const id of ['background','labels'])h.get(id).dispatch('change');
 await h.run('flushInteractions()');
 const events=h.requests[1].events;
 assert.deepEqual(events.map(e=>e.action),['drag','pan','zoom','focus','reset','fit','background','labels']);
 assert.equal(events[0].details.id,'water');assert.equal(events[0].details.x,10);
 assert.equal(events[1].details.pan_x,100);assert.equal(events[2].details.zoom,2);
});

test('large queues are batched without dropping events',async()=>{
 const h=harness();await new Promise(setImmediate);
 h.run("for(let i=0;i<120;i++)logInteraction('zoom',{zoom:i})");
 await h.run('flushInteractions()');await h.run('flushInteractions()');await h.run('flushInteractions()');
 assert.deepEqual(h.requests.slice(1).map(r=>r.events.length),[50,50,20]);
 assert.equal(h.run('interactionQueue.length'),0);
});
