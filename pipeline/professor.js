'use strict';
const $=id=>document.getElementById(id);
const el=(tag,text,cls)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(cls)node.className=cls;return node;};
let catalog={students:[],topics:[]},student=null,active=null,reviewId=null,busy=false,pending=null;
let quizStartChoice=null;
let graphRun=null;
let graphReport=null,reportGeneration=0,view='professor';
const requestedRun=new URLSearchParams(location.search).get('run');
const marks={match:'Correct',related:'Partial',conflict:'Contradicted',not_demonstrated:'Not demonstrated'};
const storage={get(key){try{return JSON.parse(localStorage.getItem('professor:'+key));}catch{return null;}},set(key,value){try{localStorage.setItem('professor:'+key,JSON.stringify(value));}catch{/* Persistence remains server-owned. */}}};
const date=value=>new Date(value).toLocaleString();
const percent=value=>value===null?'Unassessed':value+'%';
const studentName=id=>catalog.students.find(s=>s.id===id)?.name||id;
const topicName=id=>catalog.topics.find(t=>t.id===id)?.title||'Historical graph';
function status(message,error=false){$('status').textContent=message;$('status').classList.toggle('error',error);}
async function api(path,body){const response=await fetch('/api/professor/'+path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});const data=await response.json();if(!response.ok){const error=new Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail));error.status=response.status;throw error;}return data;}
function controls(){
 for(const node of document.querySelectorAll('button,input,select,textarea'))node.disabled=busy;
 const blocked=busy||Boolean(pending);
 for(const id of ['start','submit-answer','hint','reveal','next'])$(id).disabled=blocked||!student;
 $('start').disabled=blocked||!$('topic').value;
 $('confirm-quiz-student').disabled=blocked||!$('quiz-student').value;
 $('retry').hidden=!pending;$('retry').disabled=busy;
 if(active){const q=active.state.question;for(const id of ['submit-answer','hint','reveal'])$(id).disabled=blocked||active.state.completed;$('next').disabled=blocked||active.state.completed||!(q.attempts||q.revealed);}
 $('graph-mode').disabled=busy||Boolean(active&&!active.state.completed);
}
async function task(work){if(busy)return;busy=true;controls();try{await work();}catch(error){status(error.message,true);}finally{busy=false;controls();}}
function roster(){
 $('student-count').textContent=catalog.students.length;$('roster').replaceChildren();
 for(const s of catalog.students.filter(s=>s.name.toLowerCase().includes($('student-search').value.toLowerCase()))){const button=el('button',s.name,s.id===student?'active':'');button.onclick=()=>task(()=>selectStudent(s.id));$('roster').append(button);}
 $('class-view').classList.toggle('active',!student);
 controls();
}
async function refresh(){
 catalog=await api('catalog');$('warnings').hidden=!catalog.warnings.length;$('warnings').textContent=catalog.warnings.join('\n');
 const previous=$('topic').value||requestedRun;$('topic').replaceChildren();
 const latest=new Set(catalog.topics.map(t=>t.id));
 catalog.topics.push(...(catalog.versions||[]).filter(t=>!latest.has(t.id)));
 for(const topic of catalog.topics){const option=el('option',topic.title+(latest.has(topic.id)?'':' · '+topic.run_name));option.value=topic.id;$('topic').append(option);}
 if(catalog.topics.some(t=>t.id===previous))$('topic').value=previous;
 if(student&&!catalog.students.some(s=>s.id===student))student=null;
 roster();await topicChanged();await analytics();if(student)await history();
 if(!catalog.topics.length)status('No completed input runs found. Complete a pipeline run, then refresh topics.');
}
async function selectStudent(id){
 student=id;active=null;reviewId=null;storage.set('student',id);storage.set('active',null);
 $('graph-mode').value=id?'knowledge':'class';showView('professor');
 $('quiz').hidden=true;$('review').hidden=true;roster();
 $('view-label').textContent=id?'STUDENT OVERVIEW':'CLASS OVERVIEW';
 $('view-title').textContent=id?studentName(id):'Learning, made visible.';
 $('view-description').textContent=id?'Personalized practice, evidence, and progress.':'See what has been assessed and where to go next.';
 $('assessment-area').hidden=false;$('history-area').hidden=!id;
 await topicChanged();await analytics();if(id)await history();status('');
}
async function topicChanged(){
 if(active&&active.run_id!==$('topic').value){active=null;storage.set('active',null);$('quiz').hidden=true;}
 const topic=catalog.topics.find(t=>t.id===$('topic').value);$('focus').replaceChildren(el('option','Recommended from student history'));
 $('focus').firstChild.value='';
 if(!topic){$('topic-info').textContent='No completed graphs are available.';return;}
 for(const node of [...topic.concepts].sort((a,b)=>a.label.localeCompare(b.label))){const option=el('option',node.label);option.value=node.id;$('focus').append(option);}
 $('topic-info').textContent=topic.run_name+' · '+topic.relationships+' facts · '+topic.status.replaceAll('_',' ');
 if(student&&topic.concepts.length){const r=await api('recommendation/'+student+'/'+topic.id);$('recommendation').textContent=r.reason+': '+r.label+'.';}
 else $('recommendation').textContent='';
 await loadGraphReport(topic.id);await runResults();
 if(!active)setGraph(topic.id);
}
function setGraph(run,label=''){
 graphRun=run;
 const current=active?.run_id||$('topic').value;
 $('graph-return').hidden=run===current;
 $('graph-context').textContent=label?'Viewing saved run: '+label:'Exploration is temporary. Student knowledge is saved separately for this graph version.';
 const path='/professor/graph/'+encodeURIComponent(run)+'?embedded=true';
 if($('graph').getAttribute('src')!==path)$('graph').src=path;else graphCoverage();
 if(graphReport?.run_id!==run)loadGraphReport(run).catch(error=>status(error.message,true));
}
function graphCoverage(){
 const quiz=active?.run_id===graphRun&&!active.state.completed;
 const mode=quiz?'knowledge':$('graph-mode').value;
 const report=graphReport?.run_id===graphRun?graphReport:null;
 const state=quiz?active.state:mode==='knowledge'&&student?report?.state:null;
 $('graph-mode').disabled=busy||Boolean(quiz);
 $('overlay-details').hidden=mode!=='class';
 $('graph').contentWindow?.postMessage({type:'professor-coverage',state:state||null,overlay:mode==='class'?report?.overlay:null},location.origin);
}
$('graph').addEventListener('load',graphCoverage);
$('graph-return').onclick=()=>setGraph(active?.run_id||$('topic').value);
window.addEventListener('message',event=>{
 if(event.origin!==location.origin||event.source!==$('graph').contentWindow||event.data?.type!=='professor-graph-height')return;
 const height=event.data.height;
 if(Number.isFinite(height)&&height>0)$('graph').style.height=Math.ceil(Math.min(20000,height))+'px';
});
function metric(value,label){const box=el('div',undefined,'metric');box.append(el('strong',String(value)),el('span',label));return box;}
async function analytics(){
 const data=await api('analytics'+(student?'?student_id='+student:''));
 $('metrics').replaceChildren(metric(student?data.topics.filter(t=>t.score!==null).length:data.student_count,student?'Topics assessed':'Students'),metric(data.assessment_count,'Assessments with scored answers'),metric(data.answer_count,'Answer attempts saved'));
 $('insights').replaceChildren();
 for(const [label,value] of [['Strongest assessed',data.strongest.join(', ')||'No evidence yet'],['Weakest assessed (relative)',data.weakest.join(', ')||'No evidence yet'],['Suggested review',data.review_topics.map(t=>t.title+' ('+t.score+'%)').join(', ')||'No demonstrated gaps yet'],['Not yet assessed',data.unassessed.join(', ')||'All input topics assessed']]){const card=el('div',label,'insight');card.append(el('strong',value));$('insights').append(card);}
 $('topic-analytics').replaceChildren();
 for(const topic of data.topics){
  const tr=el('tr'),name=el('td',topic.title);name.append(el('small',topic.run_name));
  const value=el('td',percent(topic.score),topic.score===null?'unassessed':'score');
  if(!student)value.append(el('small',topic.assessed_students+' assessed · '+topic.unassessed_students+' unassessed students'));
  const count=el('td',topic.assessment_count+' / '+topic.answer_count);count.append(el('small',topic.completed_count+' completed · '+topic.started_count+' started'));
  const cov=topic.coverage.reduce((acc,c)=>{for(const k of ['assessed','total','independent','assisted','unassessed'])acc[k]+=c[k];return acc;},{assessed:0,total:0,independent:0,assisted:0,unassessed:0});
  const coverage=el('td',cov.assessed+' / '+cov.total+' facts assessed');coverage.append(el('small',cov.independent+' correct independently · '+cov.assisted+' with help · '+cov.unassessed+' unassessed'));
  const action=el('td');if(student){const button=el('button',topic.score===null?'Assess':'Practice','secondary');button.onclick=()=>task(async()=>{$('topic').value=topic.id;await topicChanged();$('assessment-area').scrollIntoView({behavior:'smooth'});});action.append(button);}else action.textContent=topic.score===null?'Assess students':topic.score<100?'Review gaps':'Revisit over time';
  tr.append(name,value,count,coverage,action);$('topic-analytics').append(tr);
 }
 if(!data.topics.length){const tr=el('tr'),td=el('td','No completed input topics yet.');td.colSpan=5;tr.append(td);$('topic-analytics').append(tr);}
 renderTrends(data.topics);
 if($('topic').value)await loadGraphReport(active?.run_id||$('topic').value);
 controls();
}
function renderTrends(topics){
 $('trends').replaceChildren();
 for(const topic of topics.filter(t=>t.trend.length)){
  const section=el('div',undefined,'trend-topic');section.append(el('h3',topic.title));
  {const series=student?topic.trend:topic.class_trend;const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 700 130');svg.setAttribute('role','img');svg.setAttribute('aria-label',topic.title+' '+(student?'assessment scores':'class average')+' over time; details follow.');
   const points=series.map((v,i)=>[25+i*650/Math.max(1,series.length-1),110-v.score]);
   const line=document.createElementNS(ns,'polyline');line.setAttribute('points',points.map(p=>p.join(',')).join(' '));line.setAttribute('fill','none');line.setAttribute('stroke','#78b6ff');line.setAttribute('stroke-width','2');svg.append(line);
   points.forEach(([x,y],i)=>{const dot=document.createElementNS(ns,'circle');dot.setAttribute('cx',x);dot.setAttribute('cy',y);dot.setAttribute('r',4);dot.setAttribute('fill','#78b6ff');const title=document.createElementNS(ns,'title');title.textContent=date(series[i].at)+': '+series[i].score+'%'+(student?'':' · '+series[i].assessed_students+' students assessed');dot.append(title);svg.append(dot);});section.append(svg);
   if(!student)section.append(el('p','Class trend: each assessed student’s latest score at each assessment, weighted equally. Unassessed students are excluded.','fine'));
  }
  const list=el('ol');for(const point of topic.trend){const item=el('li',date(point.at)+' · '+studentName(point.student_id)+' · '+point.score+'% · '+point.assisted_answers+' assisted answers');const link=el('a',point.run_name);link.href='/professor/graph/'+point.run_id;link.onclick=event=>{event.preventDefault();setGraph(point.run_id,point.run_name);$('graph-details').scrollIntoView({behavior:'smooth'});};const small=el('small');small.append(link);item.append(small);list.append(item);}section.append(list);$('trends').append(section);
 }
 if(!$('trends').children.length)$('trends').append(el('p','Progress will appear after the first scored answer.'));
}
async function history(){
 const rows=await api('students/'+student+'/history');$('history').replaceChildren();
 for(const row of [...rows].reverse()){
  const div=el('div',undefined,'history-item'),description=el('div',row.topic_title+' · '+percent(row.score));description.append(el('small',date(row.created_at)+' · '+row.question_count+' questions · '+row.answer_count+' attempts · '+(row.completed?'Completed':'In progress')),el('small',row.run_name));
  const actions=el('div',undefined,'actions'),inspect=el('button','Inspect answers','secondary');inspect.onclick=()=>task(()=>review(row.id));actions.append(inspect);
  if(!row.completed){const resume=el('button','Resume');resume.onclick=()=>task(async()=>{display(await api('sessions/'+row.id));$('assessment-area').scrollIntoView({behavior:'smooth'});});actions.append(resume);}
  div.append(description,actions);$('history').append(div);
 }
 if(!rows.length)$('history').append(el('p','No assessments yet. Choose a topic to begin.'));
 controls();
}
function display(result){
 const changed=active?.state.question.id!==result.state.question.id;
 active=result;storage.set('active',{id:result.id,student_id:result.student_id});$('quiz').hidden=false;
 const state=result.state,q=state.question;$('question').textContent=q.text;$('quiz-progress').textContent='Question '+q.number+' of '+state.limit;
 $('quiz-run').textContent='Student: '+studentName(result.student_id)+' · run '+result.run_id.slice(0,12);
 $('feedback').textContent=q.feedback||'';if(result.answer_score!==undefined&&result.answer_score!==null)$('feedback').textContent+=' Requested facts: '+result.answer_score+'%.';
 $('help').textContent=q.help_text||'';$('help').hidden=!q.help_text;
 $('answer-form').hidden=state.completed;$('quiz-complete').hidden=!state.completed;
 $('quiz-complete').textContent=state.completion_reason||'Assessment complete. Answers and progress are saved. Enable review mode, choose another topic, or start another quiz for remaining gaps.';
 $('next').textContent=q.number===state.limit?'Finish assessment':'Next question';
 if(changed)$('answer').value='';
 if(result.pending_answers?.length){
  pending=result.pending_answers[0].request;storage.set('pending',pending);
  $('answer').value=pending.text;
  status('This answer is saved and awaiting grading. Use Retry pending request to grade the same submission.');
 }
 $('graph-mode').value='knowledge';setGraph(result.run_id);graphCoverage();controls();
}
async function chooseQuizStudent(){
 if(pending)return;
 const choice={run_id:$('topic').value,focus_id:$('focus').value||null,review_mode:$('review-mode').checked};
 const current=await api('catalog');catalog.students=current.students;roster();
 const placeholder=el('option','Choose a student…');placeholder.value='';placeholder.disabled=true;
 $('quiz-student').replaceChildren(placeholder);
 for(const entry of catalog.students){
  const duplicate=catalog.students.filter(s=>s.name===entry.name).length>1;
  const option=el('option',entry.name+(duplicate?' · '+entry.id.slice(0,8):''));option.value=entry.id;$('quiz-student').append(option);
 }
 $('quiz-student').value='';quizStartChoice=choice;
 $('quiz-student-note').textContent=catalog.students.length?'This choice applies to the new quiz. Existing quizzes keep their original student.':'No students have been created. Cancel and add a student using the sidebar.';
 $('quiz-student-dialog').showModal();
}
async function command(action,startChoice=null){
 if(!pending){
  if(action==='start'&&!startChoice?.student_id)throw new Error('Choose a student before starting a quiz.');
  pending={action,request_id:crypto.randomUUID()};
  if(action==='start')Object.assign(pending,startChoice);
  else {pending.session_id=active.id;pending.question_id=active.state.question.id;if(action==='answer')pending.text=$('answer').value.trim();}
  storage.set('pending',pending);
 }
 if(pending.action==='start'){
  await selectStudent(pending.student_id);
  $('topic').value=pending.run_id;await topicChanged();
  $('graph-mode').value='knowledge';graphCoverage();
 }
 status('Preparing or assessing this question… Your existing history is saved.');
 try{const result=await api('quiz',pending);pending=null;storage.set('pending',null);
  if(student!==result.student_id)await selectStudent(result.student_id);
  display(result);await analytics();await history();status('Assessment saved.');
 }catch(error){if([400,404,422].includes(error.status)){pending=null;storage.set('pending',null);}throw error;}
}
async function review(id){
 reviewId=id;const data=await api('sessions/'+id);$('review').hidden=false;$('answers').replaceChildren();
 $('review-meta').textContent=studentName(data.student_id)+' · '+date(data.created_at)+' · run '+data.run_id;
 for(const answer of data.answers){
  const card=el('article',undefined,'answer-card');card.append(el('h3','Question '+answer.question.number+': '+answer.question.text),el('p',answer.text,'answer-text'));
  card.append(el('p','Score: '+percent(answer.score)+' · original model score: '+percent(answer.original_score)+' · '+(answer.helped?'Assisted answer':'Independent answer')));
  card.append(el('p',answer.effective_feedback));
  const details=el('details'),summary=el('summary','Expected answer & grading evidence');details.append(summary,el('p',answer.question.expected_answer));
  details.append(el('pre',JSON.stringify(answer.result,null,2)));card.append(details);
  if(answer.overrides.length){const audit=el('details');audit.append(el('summary','Override history ('+answer.overrides.length+')'));for(const item of answer.overrides)audit.append(el('p',date(item.created_at)+' · '+item.reason+' · '+item.feedback));card.append(audit);}
  if(answer.question.examiner_material.facts.length){
   const form=el('form',undefined,'override');form.append(el('h4','Override grading'));const selects={};
   for(const fact of answer.question.examiner_material.facts){const row=el('div',undefined,'rubric'),select=el('select');select.id='grade-'+answer.id+'-'+Object.keys(selects).length;
    const label=el('label',fact.source+' '+fact.relation.replaceAll('_',' ')+' '+fact.target+(fact.conditions?' · '+fact.conditions:''));label.htmlFor=select.id;
    for(const [value,text] of Object.entries(marks)){const option=el('option',text);option.value=value;select.append(option);}select.value=answer.effective_marks[fact.id];selects[fact.id]=select;row.append(label,select);form.append(row);}
   const feedback=el('textarea'),reason=el('textarea');feedback.id='feedback-'+answer.id;reason.id='reason-'+answer.id;feedback.required=reason.required=true;feedback.maxLength=3000;reason.maxLength=1500;feedback.rows=reason.rows=2;feedback.value=answer.effective_feedback;
   const fl=el('label','Feedback for the student');fl.htmlFor=feedback.id;const rl=el('label','Reason for this override (saved in audit history)');rl.htmlFor=reason.id;
   const save=el('button','Save override');save.type='submit';form.append(fl,feedback,rl,reason,save);
   form.onsubmit=event=>{event.preventDefault();task(async()=>{await api('answers/'+answer.id+'/override',{marks:Object.fromEntries(Object.entries(selects).map(([id,select])=>[id,select.value])),feedback:feedback.value,reason:reason.value});await review(data.id);await analytics();await history();if(active?.id===data.id)display(await api('sessions/'+data.id));status('Override saved. Original grading and audit history retained.');});};card.append(form);
  }else card.append(el('p','This question has no fact rubric and is unscored.'));
  $('answers').append(card);
 }
 if(!data.answers.length)$('answers').append(el('p','No answers have been submitted. Hints and reveals alone are not assessments.'));
 $('review').scrollIntoView({behavior:'smooth'});
 controls();
}
$('student-form').onsubmit=event=>{event.preventDefault();task(async()=>{const added=await api('students',{name:$('student-name').value});$('student-name').value='';await refresh();await selectStudent(added.id);status('Student added.');});};
$('student-search').oninput=roster;
$('class-view').onclick=()=>task(()=>selectStudent(null));
$('refresh').onclick=()=>task(async()=>{await refresh();status('Latest completed topics loaded.');});
$('topic').onchange=()=>task(async()=>{await topicChanged();await analytics();});
$('start').onclick=()=>task(chooseQuizStudent);
$('quiz-student').onchange=controls;
$('cancel-quiz-student').onclick=()=>{$('quiz-student-dialog').close();quizStartChoice=null;};
$('quiz-student-dialog').addEventListener('cancel',()=>{quizStartChoice=null;});
$('quiz-student-form').onsubmit=event=>{
 event.preventDefault();
 if(busy||pending||!quizStartChoice||!$('quiz-student').value)return;
 const choice={...quizStartChoice,student_id:$('quiz-student').value};
 quizStartChoice=null;$('quiz-student-dialog').close();task(()=>command('start',choice));
};
$('answer-form').onsubmit=event=>{event.preventDefault();task(()=>command('answer'));};
for(const action of ['hint','reveal','next'])$(action).onclick=()=>task(()=>command(action));
$('retry').onclick=()=>task(()=>command(pending.action));
$('close-review').onclick=()=>{$('review').hidden=true;reviewId=null;};
function showView(next){
 view=next;$('professor-view').hidden=next!=='professor';$('run-results').hidden=next!=='results';
 for(const [id,name] of [['professor-tab','professor'],['results-tab','results']]){
  $(id).setAttribute('aria-pressed',String(next===name));$(id).classList.toggle('secondary',next!==name);
 }
}
$('professor-tab').onclick=()=>showView('professor');
$('results-tab').onclick=()=>showView('results');
$('graph-mode').onchange=graphCoverage;
const available=value=>value===null||value===undefined?'Unavailable':String(value);
const pct=value=>value===null||value===undefined?'Unavailable':value+'%';
const duration=value=>value===null||value===undefined?'Unavailable':value<60?value.toFixed(1)+' s':(value/60).toFixed(1)+' min';
function bar(label,value,max=100){
 const row=el('div',undefined,'chart-row');row.append(el('span',label));
 const meter=el('meter');meter.min=0;meter.max=max||1;meter.value=value??0;meter.setAttribute('aria-label',label);row.append(meter,el('span',available(value)));return row;
}
async function runResults(){
 const run=$('topic').value;if(!run)return;
 const data=await api('runs/'+run+'/results');if(run!==$('topic').value)return;
 $('results-meta').textContent=[data.run_name,data.input_topic||data.input||'Topic unavailable',data.date?date(data.date):'Date unavailable',data.status||'Status unavailable'].join(' · ');
 $('run-cards').replaceChildren(...[[duration(data.duration),'Total runtime'],[available(data.nodes),'Graph concepts'],[available(data.edges),'Graph relationships'],[available(data.accepted),'Background facts accepted'],[available(data.rejected),'Background facts rejected'],[available(data.unresolved),'Unresolved items']].map(([v,l])=>metric(v,l)));
 $('run-steps').replaceChildren();$('step-chart').replaceChildren();
 const max=Math.max(1,...data.steps.map(s=>s.duration||0));
 for(const step of data.steps){
  const row=el('tr');for(const value of [step.name,step.status||'Unavailable',duration(step.duration),Object.entries(step.counts).map(([k,v])=>k.replaceAll('_',' ')+': '+available(v)).join(' · ')||'Unavailable'])row.append(el('td',value));$('run-steps').append(row);
  const chart=bar(step.name,step.duration,max);chart.lastChild.textContent=duration(step.duration);$('step-chart').append(chart);
 }
 $('reconstruction-scores').replaceChildren(metric(data.reconstruction_score==null?'Unavailable':data.reconstruction_score.toFixed(2)+' / 100','Complete-text reconstruction score'));
 for(const [key,entry] of Object.entries(data.scores||{})){
  if(key==='final_score')continue;
  const value=typeof entry==='object'?entry?.mean:entry;
  $('reconstruction-scores').append(metric(value==null?'Unavailable':Number(value).toFixed(3),key.replaceAll('_',' ')+(entry?.n!==undefined?' · n='+entry.n:'')));
 }
 $('score-definition').textContent=(data.interpretation||'Score interpretation unavailable.')+' Metric version: '+available(data.metric_version)+'. Component summaries describe chunks.';
 $('original-text').textContent=data.original??'Unavailable';$('reconstructed-text').textContent=data.reconstructed??'Unavailable';
}
function progressChart(points){
 const container=el('div',undefined,'trend-topic');
 if(!points.length){container.append(el('p','No assessed answers on this version yet.'));return container;}
 const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 700 130');svg.setAttribute('role','img');svg.setAttribute('aria-label','Coverage in green and answer performance in blue over time. Exact values follow.');
 for(const [key,color] of [['knowledge_coverage','#54d99a'],['average_score','#78b6ff']]){
  const series=points.map((p,i)=>({p,x:25+650*i/Math.max(1,points.length-1)})).filter(({p})=>p[key]!=null);
  const line=document.createElementNS(ns,'polyline');line.setAttribute('points',series.map(({p,x})=>x+','+(110-p[key])).join(' '));line.setAttribute('fill','none');line.setAttribute('stroke',color);line.setAttribute('stroke-width','2');svg.append(line);
  for(const {p,x} of series){const dot=document.createElementNS(ns,'circle');dot.setAttribute('cx',x);dot.setAttribute('cy',110-p[key]);dot.setAttribute('r',3);dot.setAttribute('fill',color);svg.append(dot);}
 }
 container.append(el('p','Green: knowledge coverage. Blue: average answer score. Both use a 0–100% scale.','fine'),svg);const list=el('ol');
 for(const p of points)list.append(el('li',(p.at?date(p.at):p.label)+' · coverage '+pct(p.knowledge_coverage)+' · performance '+pct(p.average_score)+(p.assessed_students!==undefined?' · '+p.assessed_students+'/'+p.students+' students assessed':'')));
 container.append(list);return container;
}
async function loadGraphReport(run){
 const generation=++reportGeneration;
 const data=await api('runs/'+run+'/knowledge'+(student?'?student_id='+student:''));
 if(generation!==reportGeneration)return;graphReport=data;
 $('metrics').replaceChildren(metric(student?data.selected?.metrics.assessed??0:data.students.length,student?'Relationships assessed in this version':'Students'),metric(data.assessment_count,'Assessments in this version'),metric(data.answer_count,'Answer attempts in this version'));
 $('knowledge-title').textContent=student?studentName(student)+' — saved knowledge':'Class Overview';
 $('version-note').textContent='Graph version: '+data.run_name+'. Only this version contributes to scores and class comparisons. Exact transferred facts retain their source evidence.';
 $('comparison-wrap').hidden=Boolean(student);
 $('student-comparison').replaceChildren();
 for(const row of data.students){
  const m=row.metrics,tr=el('tr'),name=el('td'),button=el('button',row.name,'secondary');button.onclick=()=>task(()=>selectStudent(row.id));name.append(button);tr.append(name);
  for(const text of [pct(m.knowledge_coverage)+' / '+pct(m.assessment_coverage),pct(m.independent_score)+' (n='+m.independent_answers+') / '+pct(m.assisted_score)+' (n='+m.assisted_answers+')',pct(m.connected_understanding),m.mastered_components+' / '+m.isolated_mastered_concepts,available(m.concentration)])tr.append(el('td',text));
  $('student-comparison').append(tr);
 }
 const fields=[['knowledge_coverage','Knowledge coverage'],['assessment_coverage','Assessment coverage'],['average_score','Answer performance'],['independent_score','Independent answers'],['assisted_score','Assisted answers'],['connected_understanding','Connected understanding'],['mastered_components','Mastered components'],['isolated_mastered_concepts','Isolated mastered concepts'],['concentration','Topic concentration (HHI)']];
 $('knowledge-metrics').replaceChildren();
 for(const [key,label] of fields){
  const value=student?data.selected?.metrics[key]:data.averages[key].value;
  const suffix=student?(key==='independent_score'?' · n='+data.selected.metrics.independent_answers:key==='assisted_score'?' · n='+data.selected.metrics.assisted_answers:''):' · n='+data.averages[key].n;
  const formatted=['mastered_components','isolated_mastered_concepts','concentration'].includes(key)?available(value):pct(value);
  $('knowledge-metrics').append(metric(formatted,label+suffix));
 }
 const topics=student?(data.selected?.metrics.topics||[]):data.topics;
 const ranked=topics.filter(t=>t.assessed_score!==null).sort((a,b)=>a.assessed_score-b.assessed_score);
 $('topic-ranking').textContent=ranked.length?'Strongest assessed: '+ranked.filter(t=>t.assessed_score===ranked.at(-1).assessed_score).map(t=>t.title).join(', ')+'. Weakest assessed (relative): '+ranked.filter(t=>t.assessed_score===ranked[0].assessed_score).map(t=>t.title).join(', ')+'. Unassessed areas are listed separately below.':'No assessed topics yet. Unassessed material is not incorrect.';
 $('community-coverage').replaceChildren();
 for(const topic of topics){const row=bar(topic.title,topic.knowledge_coverage);row.lastChild.textContent=pct(topic.knowledge_coverage);$('community-coverage').append(row,el('p',topic.assessed+'/'+topic.total+' relationship assessments · '+topic.unassessed+' unassessed · assessed score '+pct(topic.assessed_score)+(topic.assessed_students!==undefined?' · n='+topic.assessed_students+' students':''),'fine'));}
 $('knowledge-progress').replaceChildren(progressChart(student?(data.selected?.progress||[]):data.progress));
 $('metric-definitions').replaceChildren();for(const [label,text] of Object.entries(data.definitions))$('metric-definitions').append(el('dt',label),el('dd',text));
 $('overlay-counts').replaceChildren();const nodes=Object.fromEntries(data.graph.nodes.map(n=>[n.id,n.label]));
 for(const row of data.overlay)$('overlay-counts').append(el('p',nodes[row.source]+' → '+row.label+' → '+nodes[row.target]+': '+row.known+'/'+row.students+' independently know; '+row.assessed+'/'+row.students+' assessed.'));
 controls();graphCoverage();
}
task(async()=>{const remembered=storage.get('active');student=storage.get('student');await refresh();await selectStudent(student);if(remembered&&remembered.student_id===student){try{const saved=await api('sessions/'+remembered.id);if(!requestedRun||saved.run_id===requestedRun)display(saved);}catch(error){status(error.message,true);}}pending=storage.get('pending');if(pending)status('A request is awaiting confirmation. Retry it safely to recover its saved result.');if(requestedRun){$('assessment-area').scrollIntoView();}});
