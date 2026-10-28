/* Loaded only by the local server; the saved offline viewer stays unchanged. */
'use strict';
document.body.classList.add('explorer-enabled');
let quizMode=false,quizFinished=false;
const pageId=crypto.randomUUID(),interactionQueue=[];
$('search').maxLength=1500;
let interactionSequence=0,interactionSending=false;
function viewState(){return {selected,focus,zoom,pan_x:panX,pan_y:panY,search:$('search').value,
 background:$('background').checked,labels:$('labels').checked,visible_nodes:visible.length,visible_edges:links.length}}
function logInteraction(action,details={}){
 interactionQueue.push({sequence:++interactionSequence,timestamp:new Date().toISOString(),action,details});
}
async function flushInteractions(leaving=false){
 if(!interactionQueue.length||interactionSending&&!leaving)return;
 const events=[];
 for(const event of interactionQueue.slice(0,50)){
  if(new TextEncoder().encode(JSON.stringify([...events,event])).length>48000)break;
  events.push(event);
 }
 if(!events.length)return;
 if(!leaving)interactionSending=true;
 try{
  const response=await fetch($('explorer').dataset.eventsEndpoint,{method:'POST',
   headers:{'Content-Type':'application/json'},body:JSON.stringify({page_id:pageId,events}),keepalive:leaving});
  if(!response.ok)throw new Error('Logging request failed');
  const saved=new Set(events.map(event=>event.sequence));
  for(let i=interactionQueue.length-1;i>=0;i--)if(saved.has(interactionQueue[i].sequence))interactionQueue.splice(i,1);
  $('logging-status').textContent='Interactions saved to this run.';
 }catch(error){$('logging-status').textContent='Interaction logging unavailable. Keep this page open while saving retries.'}
 finally{if(!leaving)interactionSending=false}
}
setInterval(()=>flushInteractions(),500);
const originalDetails=details;
details=function(item,isEdge=false){
 originalDetails(item,isEdge);
 if(quizMode){
  $('detail-title').textContent=isEdge?'Quiz':item.label;$('details').replaceChildren();
  $('hint').hidden=false;$('hint').textContent='Use Hint or Reveal for help. The examiner view contains the stored facts and grading details.';
 }
 logInteraction('select',{kind:isEdge?'edge':'node',id:item.id,...viewState()});
};
for(const id of ['search','query-text'])$(id).addEventListener('input',()=>
 logInteraction(id==='search'?'search':'query_edit',{text:$(id).value,...viewState()}));
for(const id of ['background','labels'])$(id).addEventListener('change',()=>logInteraction(id,viewState()));
for(const id of ['focus','reset','fit'])$(id).addEventListener('click',()=>logInteraction(id,viewState()));
let gesture=null;
// Capture before node handlers stop propagation; identify the node from the DOM.
svg.addEventListener('pointerdown',event=>{
 if(event.target.closest('.edge')){gesture=null;return}
 const element=event.target.closest('.node'),node=visible.find(item=>item.element===element);
 gesture={x:event.clientX,y:event.clientY,node:node?.id,start:viewState()};
},true);
function finishGesture(event){
 if(!gesture)return;
 const start=gesture;gesture=null;
 if(event.clientX!==start.x||event.clientY!==start.y){
  const node=start.node?byId.get(start.node):null;
  logInteraction(node?'drag':'pan',{id:node?.id,x:node?.x,y:node?.y,start:start.start,
   cancelled:event.type==='pointercancel',...viewState()});
 }
}
svg.addEventListener('pointerup',finishGesture);
svg.addEventListener('pointercancel',finishGesture);
svg.addEventListener('wheel',event=>logInteraction('zoom',{delta_y:event.deltaY,...viewState()}),{passive:true});
window.addEventListener('resize',()=>logInteraction('resize',{width:innerWidth,height:innerHeight,...viewState()}));
document.addEventListener('scroll',event=>{
 const target=event.target===document?document.scrollingElement:event.target;
 logInteraction('scroll',{target:target.id||target.tagName,x:target.scrollLeft,y:target.scrollTop});
},true);
document.addEventListener('click',event=>{
 const link=event.target.closest('a');if(link)logInteraction('navigate',{href:link.getAttribute('href')});
});
document.addEventListener('visibilitychange',()=>{
 logInteraction('visibility',{state:document.visibilityState});
 if(document.visibilityState==='hidden')flushInteractions(true);
});
window.addEventListener('pagehide',event=>{logInteraction('page_hide',{persisted:event.persisted});flushInteractions(true)});
window.addEventListener('pageshow',event=>{logInteraction('page_show',{persisted:event.persisted});flushInteractions()});
logInteraction('page_open',{run_id:data.run_id,...viewState()});
flushInteractions();
const matchColors={match:'#54d99a',related:'#f3bf62',conflict:'#ff7e8b'};
const matchNames={match:'Match',related:'Related',conflict:'Conflict'};
const nodeMatches=new Map(),edgeMatches=new Map();
let queryGeneration=0;
for(const [status,color] of [...Object.entries(matchColors),['unmapped','#62738d']]){
 const marker=el('marker',{id:'arrow-query-'+status,viewBox:'0 0 10 10',refX:9,refY:5,markerWidth:6,markerHeight:6,orient:'auto-start-reverse'},svg.querySelector('defs'));
 el('path',{d:'M 0 0 L 10 5 L 0 10 z',fill:color},marker);
}
const originalHighlight=highlight;
highlight=function(){
 originalHighlight();
 const colorFor=status=>quizMode&&status==='related'?'#f0d84f':matchColors[status];
 svg.querySelector('#arrow-query-related path').setAttribute('fill',colorFor('related'));
 const active=nodeMatches.size||edgeMatches.size, endpoints=new Set();
 for(const edge of data.edges)if(edgeMatches.has(edge.id)){endpoints.add(edge.source);endpoints.add(edge.target)}
 for(const node of visible){
  const status=nodeMatches.get(node.id),circle=node.element.querySelector('circle');
  circle.setAttribute('fill',status?colorFor(status):(quizMode?'#62738d':(node.kind==='chunk'?'#60758a':colors[node.origin])));
  circle.setAttribute('stroke',status?colorFor(status):'white');
  circle.setAttribute('stroke-width',status?4:2);
  if(active||quizMode)node.element.style.opacity=status||endpoints.has(node.id)?1:.35;
 }
 for(const edge of links){
  const status=edgeMatches.get(edge.id);
  edge.line.setAttribute('stroke',status?colorFor(status):(quizMode?'#62738d':colors[edge.origin]));
  edge.line.setAttribute('stroke-width',status?4:(edge.origin==='background'?1.8:1.2));
  edge.line.setAttribute('marker-end',`url(#arrow-${status?'query-'+status:(quizMode?'query-unmapped':edge.origin)})`);
  if(active||quizMode)edge.group.style.opacity=status?1:(quizMode ? 0.7 : 0.18);
  if(quizMode||status)edge.labelElement.style.display='';
  edge.labelElement.textContent=quizMode?edge.label.replaceAll('_',' '):relationCaption(edge);
  const tooltip=edge.group.querySelector('title');
  if(tooltip)tooltip.textContent=quizMode?edge.label.replaceAll('_',' '):relationCaption(edge)+' · '+origins[edge.origin];
 }
};
function clearMatches(){
 nodeMatches.clear();edgeMatches.clear();$('query-results').replaceChildren();highlight();
}
function showMatchResults(result){
 const panel=$('query-results');panel.replaceChildren();
 const title=document.createElement('h2');title.textContent='Input matches';panel.append(title);
 const interpretation=document.createElement('p');interpretation.className='muted';
 interpretation.textContent='Interpreted as: '+[...result.interpretation.concepts,...result.interpretation.assertions].join('; ');
 panel.append(interpretation);
 for(const match of result.matches){
  const item=match.record,card=document.createElement('div');card.className='match-result';
  card.style.setProperty('--match-color',matchColors[match.status]);
  const button=document.createElement('button');button.type='button';
  const label=match.kind==='node'?item.label:`${byId.get(item.source).label} → ${relationCaption(item)} → ${byId.get(item.target).label}`;
  button.onclick=()=>details(match.kind==='node'?byId.get(match.id):data.edges.find(e=>e.id===match.id),match.kind==='edge');
  button.textContent=(quizMode&&match.status==='related'?'Partial':matchNames[match.status])+' · '+label;
  const reason=document.createElement('p');reason.textContent=match.reason;
  const quote=document.createElement('p');quote.textContent='Your text: '+match.input_quote;
  const origin=document.createElement('p');origin.className='muted';origin.textContent=origins[item.origin]||item.origin;
  card.append(button,quote,reason,origin);
  if(item.evidence){const evidence=document.createElement('blockquote');evidence.textContent='Source: '+item.evidence;card.append(evidence)}
  panel.append(card);
 }
}
$('query-clear').onclick=()=>{
 logInteraction('query_clear');
 queryGeneration++;clearMatches();$('query-status').className='';$('query-status').textContent='Highlights cleared.';
};
$('query-text').addEventListener('keydown',event=>{
 if((event.ctrlKey||event.metaKey)&&event.key==='Enter'&&!event.isComposing){
  event.preventDefault();if(!$('query-submit').disabled)$('query-form').requestSubmit();
 }
});
$('query-form').onsubmit=async event=>{
 event.preventDefault();const text=$('query-text').value.trim();if(!text)return;
 const queryId=crypto.randomUUID();logInteraction('query_submit',{query_id:queryId,text});
 const generation=++queryGeneration;clearMatches();$('query-submit').disabled=true;
 $('query-form').setAttribute('aria-busy','true');
 $('query-status').className='loading';$('query-status').textContent='Interpreting your text and checking graph records…';
 try{
  const response=await fetch($('explorer').dataset.endpoint,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text,page_id:pageId,query_id:queryId})});
  const result=await response.json();
  if(!response.ok)throw new Error(typeof result.detail==='string'?result.detail:'The query could not be processed. Check your input and try again.');
  if(generation!==queryGeneration)return;
  for(const match of result.matches)(match.kind==='node'?nodeMatches:edgeMatches).set(match.id,match.status);
  // Reset ordinary filters so a matching background edge cannot stay hidden.
  focus=null;selected=null;$('focus').disabled=true;$('search').value='';$('background').checked=true;
  render();showMatchResults(result);
  logInteraction('query_displayed',{query_id:queryId,matches:result.matches.length,...viewState()});
  $('query-status').className='';
  $('query-status').textContent=result.matches.length
   ?`${nodeMatches.size} concepts and ${edgeMatches.size} relationships found. Checked ${result.checked_records} graph records.`
   :`No matching concepts or relationships found. Checked ${result.checked_records} graph records.`;
 }catch(error){
  logInteraction('query_error',{query_id:queryId,error:error.message});
  if(generation===queryGeneration){$('query-status').className='error';$('query-status').textContent=error.message+' You can retry.'}
 }finally{$('query-submit').disabled=false;$('query-form').setAttribute('aria-busy','false')}
};
