/* The server owns question count, traversal, grading and cumulative coverage. */
'use strict';
let quizState=null,quizBusy=false,quizPending=null;
let quizPreviousLabels=true;
const quizStorageKey='graph-quiz:'+data.run_id;
function rememberQuiz(identifier){try{sessionStorage.setItem(quizStorageKey,identifier)}catch(error){/* Storage is optional. */}}
function forgetQuiz(){try{sessionStorage.removeItem(quizStorageKey)}catch(error){/* Storage is optional. */}}

function quizControls(){
 const blocked=quizBusy||Boolean(quizPending),finished=Boolean(quizState?.completed);
 for(const id of ['quiz-start','quiz-resume','quiz-exit','quiz-submit','quiz-hint','quiz-reveal','quiz-next','quiz-continue'])$(id).disabled=blocked;
 $('quiz-answer').disabled=blocked||finished;
 for(const id of ['quiz-submit','quiz-hint','quiz-reveal'])$(id).disabled=blocked||finished;
 $('quiz-next').disabled=blocked||finished||!(quizState?.question.attempts||quizState?.question.revealed);
 $('quiz-retry').hidden=!quizPending||quizBusy;
 $('quiz-retry').disabled=quizBusy;
 $('quiz-panel').setAttribute('aria-busy',String(quizBusy));
 $('quiz-examiner-toggle').disabled=blocked||!quizState;
}

function showQuizResults(result){
 const panel=$('query-results');panel.replaceChildren();
 const title=document.createElement('h2');title.textContent='Your statements';panel.append(title);
 const labels={match:'Equivalent meaning',related:'Similar, not equivalent',conflict:'Contradiction'};
 for(const match of result.matches){
  const card=document.createElement('div');card.className='match-result';
  card.style.setProperty('--match-color',match.status==='related'?'#f0d84f':matchColors[match.status]);
  const verdict=document.createElement('strong');verdict.textContent=labels[match.status];
  const citation=document.createElement('p');citation.textContent=match.statement_id.replace('_',' ')+' — '+match.statement;
  card.append(verdict,citation);panel.append(card);
 }
 const seen=new Set();
 for(const item of result.uncredited){
  const key=item.statement_id+':'+item.reason_code;if(seen.has(key))continue;seen.add(key);
  const note=document.createElement('p');
  const reason=item.reason_code==='endpoints_not_named'
   ?'Name both things explicitly in the same statement to earn credit.'
   :item.reason_code==='assertion_not_cited'
    ?'The claimed connection could not be located in your own wording.'
    :'Write an assertion rather than a question or a list of names.';
  note.textContent=item.statement_id.replace('_',' ')+' — “'+item.statement+'” '+reason;panel.append(note);
 }
 if(!result.matches.length&&!result.uncredited.length){
  const note=document.createElement('p');note.textContent='No relevant assertion was identified in this answer.';panel.append(note);
 }
}

function displayQuiz(state){
 queryGeneration++;
 if(!quizMode)quizPreviousLabels=$('labels').checked;
 const changed=quizState?.question.id!==state.question.id;
 quizState=state;quizMode=true;quizFinished=state.completed;rememberQuiz(state.quiz_id);
 document.body.classList.add('quiz-mode');
 $('explorer-title').textContent='Map what you know';
 $('query-form').hidden=true;$('query-status').hidden=true;$('quiz-panel').hidden=false;
 $('quiz-start').hidden=true;$('quiz-resume').hidden=true;$('quiz-exit').hidden=false;
 $('related-legend').textContent='Similar meaning';
 $('match-help').textContent='Green: equivalent meaning. Yellow: similar meaning. Red: contradiction. Credit requires both names in your own statement.';
 $('quiz-progress').textContent=`Session ${state.round} · Question ${state.question.number} of ${state.limit}`;
 $('quiz-question').textContent=state.question.text;
 $('quiz-feedback').textContent=state.question.feedback||'';
 $('quiz-help').hidden=!state.question.help_text;$('quiz-help').textContent=state.question.help_text||'';
 $('quiz-examiner').hidden=true;$('quiz-examiner-content').textContent='';
 $('quiz-examiner-toggle').setAttribute('aria-expanded','false');
 $('quiz-form').hidden=state.completed;$('quiz-summary').hidden=!state.completed;
 $('quiz-next').textContent=state.question.number===state.limit?'Finish session':'Next question';
 const s=state.summary;
 $('quiz-coverage').textContent=`${s.matched} of ${s.total_relationships} relationships mapped (${s.coverage_percent}%). ${s.newly_mapped} newly mapped this session. ${s.partial} partial, ${s.contradicted} contradicted, ${s.untouched} untouched.`;
 $('quiz-breakdown').textContent=`Document: ${s.document_matched}/${s.document_total}. Background: ${s.background_matched}/${s.background_total}. Recalled without help: ${s.independent}; mapped with help only: ${s.assisted}. Revealed: ${s.revealed}. Coverage is cumulative across continued sessions.`;
 if(changed)$('quiz-answer').value='';
 nodeMatches.clear();edgeMatches.clear();
 for(const [id,status] of Object.entries(state.node_status))nodeMatches.set(id,status);
 for(const [id,status] of Object.entries(state.edge_status))edgeMatches.set(id,status);
 focus=null;selected=null;$('focus').disabled=true;$('search').value='';$('background').checked=true;
 $('labels').checked=true;$('labels').disabled=true;
 $('details').replaceChildren();$('detail-title').textContent=state.completed?'Your coverage map':'Build your map';
 $('hint').hidden=false;$('hint').textContent=state.completed?'Review your mapped relationships or continue with five more questions.':'Answer the question to color the relationships you explain.';
 render();
 if(state.last_result)showQuizResults(state.last_result);
 else $('query-results').replaceChildren();
 quizControls();
 if(changed&&!state.completed)$('quiz-answer').focus();
}

async function sendQuiz(action){
 if(quizBusy)return;
 if(!quizPending){
  if(action==='answer'&&!$('quiz-answer').value.trim())return;
  quizPending={action,request_id:crypto.randomUUID(),page_id:pageId,
   quiz_id:quizState?.quiz_id||null,question_id:quizState?.question.id||null,
   text:action==='answer'?$('quiz-answer').value.trim():''};
 }
 quizBusy=true;quizControls();
 $('quiz-status').textContent=quizPending.action==='answer'?'Reading and assessing your statements…':'Preparing your question or help…';
 try{
  const response=await fetch($('quiz-panel').dataset.endpoint,{method:'POST',
   headers:{'Content-Type':'application/json'},body:JSON.stringify(quizPending)});
  const result=await response.json();
  if(!response.ok){
   if([400,404,422].includes(response.status))quizPending=null;
   if(response.status===404){forgetQuiz();quizState=null;$('quiz-start').hidden=false}
   throw new Error(typeof result.detail==='string'?result.detail:'The quiz request could not be completed.');
  }
  quizPending=null;displayQuiz(result);$('quiz-status').textContent=result.completed?'Five questions complete. Review your coverage below.':'';
 }catch(error){
  $('quiz-status').textContent=error.message+(quizPending?' Use Retry quiz request to safely retry this same action.':'');
 }finally{quizBusy=false;quizControls()}
}

$('quiz-start').onclick=()=>sendQuiz('start');
$('quiz-retry').onclick=()=>sendQuiz(quizPending?.action);
$('quiz-hint').onclick=()=>sendQuiz('hint');
$('quiz-reveal').onclick=()=>sendQuiz('reveal');
$('quiz-next').onclick=()=>sendQuiz('next');
$('quiz-continue').onclick=()=>sendQuiz('continue');
$('quiz-examiner-toggle').onclick=async()=>{
 if(!quizState||quizBusy)return;
 if(!$('quiz-examiner').hidden){
  $('quiz-examiner').hidden=true;$('quiz-examiner-toggle').setAttribute('aria-expanded','false');return;
 }
 const identifier=quizState.quiz_id,question=quizState.question.id;
 $('quiz-examiner-toggle').disabled=true;
 try{
  const response=await fetch($('quiz-panel').dataset.endpoint+'/'+encodeURIComponent(identifier)+'/examiner');
  const result=await response.json();
  if(!response.ok)throw new Error(result.detail||'Could not load examiner details');
  if(quizState?.quiz_id!==identifier||quizState?.question.id!==question)return;
  $('quiz-examiner-content').textContent=JSON.stringify(result,null,2);
  $('quiz-examiner').hidden=false;$('quiz-examiner-toggle').setAttribute('aria-expanded','true');
 }catch(error){$('quiz-status').textContent=error.message}
 finally{quizControls()}
};
$('quiz-form').onsubmit=event=>{event.preventDefault();sendQuiz('answer')};
$('quiz-answer').addEventListener('input',()=>logInteraction('quiz_edit',{
 quiz_id:quizState?.quiz_id,question_id:quizState?.question.id,text:$('quiz-answer').value}));
$('quiz-answer').addEventListener('keydown',event=>{
 if((event.ctrlKey||event.metaKey)&&event.key==='Enter'&&!event.isComposing){
  event.preventDefault();if(!$('quiz-submit').disabled)$('quiz-form').requestSubmit();
 }
});
$('quiz-exit').onclick=()=>{
 quizMode=false;quizFinished=false;logInteraction('quiz_exit',{quiz_id:quizState?.quiz_id});
 document.body.classList.remove('quiz-mode');
 $('labels').disabled=false;$('labels').checked=quizPreviousLabels;
 $('quiz-panel').hidden=true;$('quiz-exit').hidden=true;$('quiz-resume').hidden=!quizState;
 $('query-form').hidden=false;$('query-status').hidden=false;$('quiz-status').textContent='';
 $('explorer-title').textContent='Ask this graph';$('related-legend').textContent='Related';
 $('match-help').textContent='A matching concept identifies a reference; it does not confirm your whole statement.';
 clearMatches();$('details').replaceChildren();$('detail-title').textContent='Explore the knowledge';
 $('hint').hidden=false;$('hint').textContent='Select a concept or relationship to inspect its details.';
};
$('quiz-resume').onclick=()=>{
 if(quizState){logInteraction('quiz_resume',{quiz_id:quizState.quiz_id});displayQuiz(quizState)}
};

// Restore the active server session after reloading this browser tab.
(async()=>{
 let identifier;try{identifier=sessionStorage.getItem(quizStorageKey)}catch(error){return}
 if(!identifier)return;
 quizBusy=true;quizControls();
 try{
  const response=await fetch($('quiz-panel').dataset.endpoint+'/'+encodeURIComponent(identifier));
  if(response.ok)displayQuiz(await response.json());
  else if(response.status===404)forgetQuiz();
  else $('quiz-status').textContent='The previous quiz is busy. Reload after its answer finishes to resume.';
 }catch(error){$('quiz-status').textContent='Could not restore the quiz. Reload to retry, or start a new session.'}
 finally{quizBusy=false;quizControls()}
})();
