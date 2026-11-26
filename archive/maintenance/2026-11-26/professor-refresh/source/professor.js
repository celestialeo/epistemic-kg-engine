const APP_UI_SETTINGS=__UI_SETTINGS__;
'use strict';
const $=id=>document.getElementById(id), el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
const storage={get(k){try{return JSON.parse(localStorage.getItem('professor:'+k));}catch{return null;}},set(k,v){try{localStorage.setItem('professor:'+k,JSON.stringify(v));}catch{}}};
const saved=storage.get('workspace')||{};
const S={tab:saved.tab||'quiz',topic:saved.topic||'',runs:saved.runs||{},student:saved.student||storage.get('student')||'',detail:Boolean(saved.detail),insight:saved.insight||'',aggregate:true,active:null,pending:storage.get('pending'),scope:null,catalog:null,busy:false,generation:0,graphMode:'knowledge',review:null,failedQuestion:null};
const pct=v=>v==null?'Unassessed':v+'%', value=v=>v==null?'Unavailable':String(v), date=v=>v?new Date(v).toLocaleString():'Date unavailable';
const duration=v=>v==null?'Unavailable':v<60?v.toFixed(1)+' s':(v/60).toFixed(1)+' min';
const marks={match:'Correct',related:'Partial',conflict:'Incorrect / contradicted',not_demonstrated:'Not demonstrated'};
function persist(){storage.set('workspace',{tab:S.tab,topic:S.topic,runs:S.runs,student:S.student,detail:S.detail,insight:S.insight});storage.set('student',S.student);}
function status(text,error=false){$('status').textContent=text;$('status').classList.toggle('error',error);}
async function api(path,body){const response=await fetch('/api/professor/'+path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});const data=await response.json();if(!response.ok){const error=new Error(typeof data.detail==='string'?data.detail:(data.detail?.message||JSON.stringify(data.detail)));error.status=response.status;error.code=data.detail?.code;throw error;}return data;}
function source(id){return S.catalog?.versions.find(r=>r.id===id);}
function studentName(id=S.student){return S.catalog?.students.find(s=>s.id===id)?.name||'Choose a student';}
function evidenceLabel(f){return f?'Evidence: '+(f.mark==='match'&&!f.helped?'independently known':f.mark)+(f.helped?' with help':'')+'; recorded '+date(f.at)+'; learned on '+runLabel(f.source_run_id):'Unassessed';}
function runLabel(id){const r=source(id);return r?r.title+' · '+r.run_name+' · ID '+r.id.slice(0,APP_UI_SETTINGS.run_id_chars):id;}
function scopeParams(student=true){const p=new URLSearchParams();if(S.topic){p.set('topic',S.topic);if(S.runs[S.topic])p.set('run_id',S.runs[S.topic]);}if(student&&S.student)p.set('student_id',S.student);return p;}
function activeInScope(){return S.active&&S.active.student_id===S.student&&S.scope?.runs.some(r=>r.id===S.active.run_id);}
function controls(){
 for(const n of document.querySelectorAll('button,input,select,textarea'))n.disabled=S.busy;
 $('topic').disabled=S.busy||!S.topic;
 $('start').disabled=S.busy||!S.student||!$('quiz-source').value||Boolean(S.pending)||Boolean(activeInScope()&&!S.active.state.completed&&!S.active.graph_review?.changed)||(!$('review-mode').checked&&!S.scope?.recommendations.some(r=>r.run_id===$('quiz-source').value));
 $('try-another-concept').hidden=!S.failedQuestion||S.tab!=='quiz'||(S.failedQuestion.student_id&&S.failedQuestion.student_id!==S.student)||(!S.failedQuestion.student_id&&S.active?.student_id!==S.student);
 $('confirm-quiz-student').disabled=S.busy||!$('quiz-student').value;
 const usable=activeInScope()&&!S.active.state.completed&&!S.active.graph_review?.changed;
 for(const id of ['submit-answer','hint','reveal'])$(id).disabled=S.busy||!usable||Boolean(S.pending)||Boolean(S.active?.state.question_mastered);
 $('next').disabled=S.busy||!usable||Boolean(S.pending)||!(S.active?.state.question.attempts||S.active?.state.question.revealed||S.active?.state.question_mastered);
 $('retry').disabled=S.busy;$('retry').hidden=!S.pending||S.pending.session_id!==S.active?.id;
 $('open-pending').textContent=S.pending?.action==='start'?'Retry quiz generation':'Open saved quiz';$('pending-banner').hidden=!S.pending;$('pending-label').textContent=S.pending?(S.pending.action==='start'?'Quiz creation is awaiting confirmation. Retrying uses the same request and will not create a duplicate quiz.':'A request is awaiting confirmation. Its original student, source graph, and submitted answer are preserved.'):'';
 for(const id of ['quiz-source','focus','review-mode'])$(id).disabled=S.busy||Boolean(usable);
 $('graph-mode').disabled=S.busy||Boolean(usable&&S.tab==='quiz');
 $('graph-mode').querySelector('[value="knowledge"]').disabled=!S.student;
 manualControls();
}
async function task(work){if(S.busy)return;S.busy=true;controls();try{await work();}catch(e){status(e.message,true);}finally{S.busy=false;controls();}}
function option(text,v){const n=el('option',text);n.value=v;return n;}
function fillSelectors(){
 $('scope-topic').replaceChildren(option('All Topics',''),...S.catalog.topics.map(r=>option(r.title,r.topic_key)));$('scope-topic').value=S.topic;
 const versions=S.catalog.versions.filter(r=>r.topic_key===S.topic);
 if(S.topic){const latest=S.catalog.topics.find(r=>r.topic_key===S.topic);if(!versions.some(r=>r.id===S.runs[S.topic]))S.runs[S.topic]=latest?.id||versions[0]?.id;$('topic').replaceChildren(...versions.map(r=>option(r.run_name+' · '+r.status.replaceAll('_',' ')+(r.id===latest?.id?' · latest':''),r.id)));$('topic').value=S.runs[S.topic];}
 else $('topic').replaceChildren(option('Latest version of each topic',''));
 $('student-select').replaceChildren(option('Choose a student',''),...S.catalog.students.map(r=>option(r.name+' · '+r.id.slice(0,APP_UI_SETTINGS.student_id_chars),r.id)));$('student-select').value=S.student;
 $('scope-note').textContent=S.topic?'This topic and graph version apply across all three tabs. History still includes its earlier versions.':'All Topics uses one latest version per input topic. Exactly matching relationships count once; topic rows can overlap and must not be added.';
 persist();
}
async function refresh(){
 S.catalog=await api('catalog');
 if(S.topic&&!S.catalog.topics.some(r=>r.topic_key===S.topic)){S.topic='';status('The previous topic is unavailable. Showing All Topics; saved history is retained.',true);}
 if(S.student&&!S.catalog.students.some(s=>s.id===S.student)){S.student='';S.detail=false;}
 if(S.pending?.student_id&&!S.catalog.students.some(s=>s.id===S.pending.student_id)){S.pending=null;storage.set('pending',null);}
 if(S.active&&!S.catalog.students.some(s=>s.id===S.active.student_id)){S.active=null;storage.set('active',null);}
 if(S.active)S.active=await api('sessions/'+S.active.id);
 $('warnings').hidden=!S.catalog.warnings.length;$('warnings').textContent=S.catalog.warnings.join('\n');fillSelectors();await loadScope();
}
async function loadScope(){const generation=++S.generation;const data=await api('scope?'+scopeParams());if(generation!==S.generation)return;S.scope=data;render();await renderGraph();if(S.tab==='insights')await runResults();await loadContributions();}
function showTab(tab){S.tab=tab;S.review=null;$('review').hidden=true;persist();render();return renderGraph().then(()=>tab==='insights'?runResults():null).then(loadContributions);}
function metric(v,label,help){const n=el('div',undefined,'metric');n.append(el('strong',String(v)),el('span',label));if(help)n.append(el('small',help));return n;}
function cards(target,m,averages=false){
 const keys=[['knowledge_coverage','Known without help','Independent unique relationships / all unique relationships.'],['assessment_coverage','Checked','Assessed unique relationships / all unique relationships.'],['average_score','Answer performance','Mean latest answer per question; includes assisted answers.']];
 $(target).replaceChildren(...keys.map(([k,label,help])=>metric(pct(averages?m?.[k]?.value:m?.[k]),label,help+(averages?' n = '+(m?.[k]?.n||0)+' students.':''))));
}
function render(){
 if(!S.scope)return;
 if(S.review&&!S.scope.history.some(row=>row.id===S.review))S.review=null;
 $('review').hidden=!S.review;
 const titles={quiz:['Quiz','Source-grounded practice, guided by the selected student’s progress.'],insights:['Run Insights','Saved pipeline results and source graphs. These are not student grades.'],class:['Class Overview','Find common patterns, then open a student for their evidence and history.']};
 for(const tab of ['quiz','insights','class']){const current=S.tab===tab;$('tab-'+tab).classList.toggle('active',current);if(current)$('tab-'+tab).setAttribute('aria-current','page');else $('tab-'+tab).removeAttribute('aria-current');$(tab+'-view').hidden=!current;}
 $('view-title').textContent=titles[S.tab][0];$('view-description').textContent=titles[S.tab][1];
 $('source-context').textContent=S.scope.runs.length?(S.topic?runLabel(S.scope.runs[0].id):S.scope.runs.length+' source versions · '+S.scope.unique_relationships+' unique relationships ('+S.scope.source_relationships+' source occurrences)'):'No saved completed graphs. Refresh after a pipeline run.';
 $('metric-definitions').replaceChildren();for(const [label,text] of Object.entries(S.scope.definitions))$('metric-definitions').append(el('dt',label),el('dd',text));
 $('open-pending').textContent=S.pending?.action==='start'?'Retry quiz generation':'Open saved quiz';$('pending-banner').hidden=!S.pending;$('pending-label').textContent=S.pending?(S.pending.action==='start'?'Quiz creation is awaiting confirmation. Retrying uses the same request and will not create a duplicate quiz.':'A request is awaiting confirmation. Its original student, source graph, and submitted answer are preserved.'):'';
 $('learning-details').hidden=S.tab==='insights';
 const previous=$('learning-source').value;$('learning-source').replaceChildren(...S.scope.runs.map(r=>option(runLabel(r.id),r.id)));if(S.scope.runs.some(r=>r.id===previous))$('learning-source').value=previous;
 renderQuiz();renderClass();renderInsights();controls();
}
function breakdown(target,rows){
 const table=el('table'),head=el('thead'),tr=el('tr');for(const label of ['Topic / source version','Known / checked','Answer score','Open'])tr.append(el('th',label));head.append(tr);table.append(head);const body=el('tbody');
 for(const row of rows){const tr=el('tr'),title=el('td',row.title);title.append(el('small',row.run_name+' · '+row.id.slice(0,APP_UI_SETTINGS.run_id_chars)));const last=el('td'),button=el('button','Open source','secondary');button.onclick=()=>task(()=>openSource(row.id));last.append(button);tr.append(title,el('td',pct(row.knowledge_coverage)+' / '+pct(row.assessment_coverage)),el('td',pct(row.average_score)),last);body.append(tr);}table.append(body);$(target).replaceChildren(table);if(!rows.length)$(target).append(el('p','No source graphs in this scope.'));
}
async function openSource(id,tab=S.tab){const r=source(id);if(!r)throw new Error('Source run is unavailable');S.topic=r.topic_key;S.runs[S.topic]=id;S.tab=tab;fillSelectors();await loadScope();status('Opened source version: '+runLabel(id));}
function fillQuizSource(){
 const previous=$('quiz-source').value, recommended=S.scope.recommendations[0]?.run_id;
 const rows=S.scope.runs;
 $('quiz-source').replaceChildren(...rows.map(r=>{const recommendation=S.scope.recommendations.find(x=>x.run_id===r.id);return option(r.title+' · '+r.run_name+(recommendation?' · '+recommendation.remaining+' unique gaps':''),r.id);}));
 $('quiz-source').value=rows.some(r=>r.id===previous)?previous:(recommended||rows[0]?.id||'');
 fillFocus();
}
function fillFocus(){const r=source($('quiz-source').value),old=$('focus').value;$('focus').replaceChildren(option('Recommended from progress',''),...(r?.concepts||[]).map(n=>option(n.label,n.id)));if([...$('focus').options].some(o=>o.value===old))$('focus').value=old;}
function renderQuiz(){
 cards('quiz-summary',S.scope.selected?.metrics);fillQuizSource();
 $('recommendation').textContent=!S.student?'Select a student before starting a quiz.':S.scope.recommendations.length?'Suggested next: '+S.scope.recommendations[0].title+' — '+S.scope.recommendations[0].remaining+' unique relationships still need independent evidence.':'No unmastered facts remain in the included graphs, or no facts are available. Enable review to revisit known material.';
 renderHistory('quiz-history',false);breakdown('quiz-breakdown',S.scope.topics);
 const visible=activeInScope();$('quiz').hidden=!visible;
 if(visible){const q=S.active.state.question,state=S.active.state;$('quiz-progress').textContent='Question '+q.number+' of '+state.limit;$('quiz-run').textContent=studentName(S.active.student_id)+' · '+runLabel(S.active.run_id);$('quiz-prior-context').textContent=S.active.scope_run_ids?.length?'This quiz retains overlapping progress from its original source set: '+S.active.scope_run_ids.map(runLabel).join('; ')+'. Topic summaries remain source-specific.':'';$('question-generation-note').textContent=state.generation_skips?.length?'Some facts were deferred after unsuccessful question drafts. Their grades did not change; they remain available in a later quiz.':'';$('question').textContent=state.question_mastered&&!q.attempts?'This material is already green from another quiz. Continue to the next question.':q.text;$('answer-form').hidden=state.completed;$('quiz-complete').hidden=!state.completed;$('quiz-complete').textContent=state.completion_reason||'Quiz complete. Your answers are saved.';$('feedback').textContent=S.active.graph_review?.changed?S.active.graph_review.message:(q.feedback||'');if(S.active.answer_score!=null)$('feedback').textContent+=' Requested facts: '+S.active.answer_score+'%.';$('help').textContent=(q.help_source==='validated_expected_answer'?'Saved validated answer: ':'')+(q.help_text||'');$('help').hidden=!q.help_text;$('next').textContent=state.question_mastered&&!q.attempts?'Continue to remaining gaps':q.number===state.limit?'Finish quiz':'Next question';}
}
function renderHistory(target,inspect){
 $(target).replaceChildren();if(!S.student){$(target).append(el('p','Choose a student to see their saved quizzes.'));return;}
 for(const row of S.scope.history){const div=el('div',undefined,'history-item'),description=el('div',row.topic_title+' · '+pct(row.score));description.append(el('small',row.run_name+' · ID '+row.run_id.slice(0,APP_UI_SETTINGS.run_id_chars)),el('small',date(row.created_at)+' · '+row.answer_count+' attempts · '+(row.completed?'Completed':'In progress')),el('small',row.included_in_metrics?'Included source version':'Historical version — retained, outside current-version metrics'));const actions=el('div',undefined,'actions');if(row.graph_changes?.length)description.append(el('small','Graph changed: historical grades retained; affected mastery needs new evidence.'));if(!row.completed){const resume=el('button',row.pending?'Resume pending answer':'Resume');resume.onclick=()=>task(()=>resumeQuiz(row.id));actions.append(resume);}const button=el('button','Inspect answers','secondary');button.onclick=()=>task(async()=>{S.detail=true;S.tab='class';persist();render();await renderGraph();await review(row.id);});actions.append(button);div.append(description,actions);$(target).append(div);}
 if(!S.scope.history.length)$(target).append(el('p','No quiz history in this topic scope. Other topics and older versions have not been deleted.'));
}
function miniGraph(row){
 const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 300 150');svg.setAttribute('role','img');svg.setAttribute('aria-label',row.name+' learning graph preview; '+S.scope.graph.nodes.length+' concepts. Exact states and sources are available in student detail.');
 const nodes=S.scope.graph.nodes.slice(0,APP_UI_SETTINGS.thumbnail_nodes ?? 30),locations=new Map(nodes.map((n,i)=>[n.id,{x:150+120*Math.cos(2*Math.PI*i/Math.max(1,nodes.length)),y:75+52*Math.sin(2*Math.PI*i/Math.max(1,nodes.length))}]));const colors={match:'#54d99a',related:'#f3bf62',conflict:'#ff7e8b',not_demonstrated:'#ff7e8b'};
 const previewEdges=S.scope.graph.edges.filter(e=>locations.has(e.source)&&locations.has(e.target)).slice(0,APP_UI_SETTINGS.thumbnail_edges ?? 60);
 svg.dataset.previewNodes=nodes.length;svg.dataset.previewEdges=previewEdges.length;svg.setAttribute('aria-label',row.name+' graph preview: '+nodes.length+' of '+S.scope.graph.nodes.length+' concepts and '+previewEdges.length+' of '+S.scope.graph.edges.length+' relationships. Open student detail for the whole graph.');
 for(const edge of previewEdges){const a=locations.get(edge.source),b=locations.get(edge.target),line=document.createElementNS(ns,'line');for(const[k,v]of Object.entries({x1:a.x,y1:a.y,x2:b.x,y2:b.y,stroke:colors[row.state.edge_status[edge.id]]||'#62738d','stroke-width':2}))line.setAttribute(k,v);svg.append(line);}
 for(const node of nodes){const p=locations.get(node.id),dot=document.createElementNS(ns,'circle');for(const[k,v]of Object.entries({cx:p.x,cy:p.y,r:4,fill:colors[row.state.node_status[node.id]]||'#62738d'}))dot.setAttribute(k,v);const title=document.createElementNS(ns,'title');title.textContent=node.label;dot.append(title);svg.append(dot);}return svg;
}
function renderClass(){
 renderClassNavigation();renderMetricExplorer();renderStudentEvidence();
 $('class-summary-view').hidden=S.detail&&Boolean(S.student);$('student-detail').hidden=!S.detail||!S.student;
 cards('class-metrics',S.scope.averages,true);
 const nodes=Object.fromEntries(S.scope.graph.nodes.map(n=>[n.id,n.label]));
 for(const [target,rows,difficult] of [['class-strengths',S.scope.strengths,false],['class-difficulties',S.scope.difficulties,true]]){const list=el('ul');for(const r of rows)list.append(el('li',nodes[r.source]+' → '+r.label+' → '+nodes[r.target]+' — '+(difficult?(r.difficulty+' partial / incorrect / not demonstrated; '+r.assisted+' correct with help'):(r.known+'/'+r.students+' independently know'))+'; '+r.assessed+'/'+r.students+' assessed'));$(target).replaceChildren(rows.length?list:el('p',difficult?'No assessed difficulties or assisted successes yet. Unassessed material is not a weakness.':'No independent evidence yet.'));}
 $('student-cards').replaceChildren();const query=$('student-search').value.toLowerCase();
 for(const row of S.scope.students.filter(r=>r.name.toLowerCase().includes(query))){const button=el('button',undefined,'student-card'),preview=miniGraph(row);button.append(el('h3',row.name),preview,el('p',pct(row.metrics.knowledge_coverage)+' known · '+pct(row.metrics.assessment_coverage)+' checked'),el('p','Answer score: '+pct(row.metrics.average_score)),el('small',row.categories.unassessed+' unassessed · '+row.categories.incorrect+' incorrect · '+row.categories.assisted_correct+' correct with help'),el('small','Preview: '+preview.dataset.previewNodes+' of '+S.scope.graph.nodes.length+' concepts / '+preview.dataset.previewEdges+' of '+S.scope.graph.edges.length+' links. Metrics cover the whole scope.'));button.onclick=()=>task(()=>openLearner(row.id));button.append(coverageBar(row.metrics.knowledge_coverage,'Known without help'),el('small','Average degree: '+metricFormat(row.graph_metrics.values.average_degree)+' · Open student →'));$('student-cards').append(button);}
 if(!S.scope.students.length)$('student-cards').append(el('p','Add a student using the sidebar. No roster or evidence has been invented.'));
 breakdown('class-breakdown',S.scope.class_topics);
 if(S.student){$('student-title').textContent=studentName();$('student-context').textContent='Learning results for '+(S.topic?(S.scope.runs[0]?.title||'selected topic'):'All Topics')+'. Source versions are shown below; historical quizzes remain available.';cards('student-metrics',S.scope.selected?.metrics);const c=S.scope.selected?.categories||{};$('student-categories').replaceChildren(...Object.entries(c).map(([k,v])=>el('span',k.replaceAll('_',' ')+': '+v)));breakdown('student-breakdown',S.scope.topics);renderHistory('history',true);}
}
const METRIC_CARDS = [
 ['relationship_coverage','01','Relationship coverage','breadth','percent','How much has been demonstrated?','Independently known relationships divided by all reference relationships. Assisted and partial answers stay separate.'],
 ['assessment_coverage','02','Assessment coverage','breadth','percent','How much has been checked?','Relationships with a resolved assessment divided by all reference relationships. Unassessed does not mean incorrect.'],
 ['concept_reach','03','Concept reach & completeness','breadth','percent','How broadly do the connections reach?','Reach counts concepts touched by an independently known fact. Completeness is the mean fraction of known incident facts per concept with reference relationships. Reach alone is not mastery.'],
 ['average_degree','04','Average degree','connections','number','How many neighbors does a concept have?','Mean distinct neighbors among demonstrated concepts. Incoming and outgoing degrees appear in the concept table. Parallel facts count as one structural connection; self-links are excluded.'],
 ['density','05','Graph density','connections','percent','How tightly connected is the graph?','Existing undirected links divided by possible links among demonstrated concepts. A small graph can be dense: always read this alongside coverage.'],
 ['components','06','Connected components','connections','number','One connected whole, or separate islands?','Separate groups of demonstrated concepts. Largest-component share shows how much of the demonstrated graph belongs to its biggest group. No demonstrated concepts means unavailable.'],
 ['clustering','07','Clustering coefficient','connections','number','Are neighboring concepts connected too?','Average fraction of closed triangles around demonstrated concepts, from 0 to 1. Degree below two contributes zero. Chains and hierarchies can legitimately have low clustering.'],
 ['cross_topic_coverage','08','Cross-community connections','topics','percent','Are knowledge areas connected?','Independently known links between fixed reference communities divided by all such reference links. Communities are structural groups, not necessarily course topics. No reference bridges means not applicable.'],
 ['global_efficiency','09','Global efficiency','connections','number','How directly do concepts connect?','Mean inverse shortest-path distance across ALL reference concepts, from 0 to 1. Unreachable pairs contribute zero. Uses undirected, unweighted paths; this is not a measure of thinking speed.'],
 ['modularity','10','Communities & modularity','topics','number','How separated are the knowledge groups?','Modularity at resolution 1 against a fixed reference partition, using simple undirected connections. Positive means more within-group links than the degree-based baseline; negative means fewer. Higher is not automatically better.'],
 ['concentration','11','Knowledge concentration','topics','number','Focused in one area, or spread across areas?','HHI: sum of squared shares of mastered facts across fixed reference communities and bridge groups. Near 1 means concentrated. Larger groups offer more facts, so compare with per-topic coverage.'],
 ['connection_strength','12','Connection strength','breadth','number','How much evidence supports each concept?','Average independently known incident facts per reference concept, including zero-evidence concepts. For the class, each fact contributes the proportion of students who independently know it. This is not model confidence.']
];
let metricFilter='breadth';
const metricFormat=(v,kind='number')=>v==null?'Unavailable':Number(v).toLocaleString(undefined,{maximumFractionDigits:kind==='percent'?1:3})+(kind==='percent'?'%':'');
function analyticsTable(headers,rows){
 const wrap=el('div',undefined,'table-scroll'),table=el('table'),head=el('thead'),tr=el('tr'),body=el('tbody');
 headers.forEach(t=>{const th=el('th',t);th.scope='col';tr.append(th);});head.append(tr);table.append(head);
 rows.forEach(values=>{const row=el('tr');values.forEach(v=>{const cell=el('td');if(v instanceof Node)cell.append(v);else cell.textContent=v;row.append(cell);});body.append(row);});
 table.append(body);wrap.append(table);return wrap;
}
function coverageBar(v,label){const wrap=el('div',undefined,'coverage-track'),bar=el('span');bar.style.width=(v||0)+'%';wrap.setAttribute('role','img');wrap.setAttribute('aria-label',label+': '+metricFormat(v,'percent'));wrap.append(bar);return wrap;}
async function openLearner(id){S.student=id;S.detail=true;S.graphMode='knowledge';S.review=null;fillSelectors();await loadScope();$('student-title').focus({preventScroll:true});$('class-view').scrollIntoView();}
function renderMetricExplorer(){
 const a=S.scope.analytics;if(!a)return;
 const cohort=!S.detail||!S.scope.selected, profile=cohort?null:S.scope.selected.graph_metrics;
 const read=k=>cohort?a.averages[k]?.value:profile?.values[k];
 $(cohort?'class-analysis-host':'student-analysis-host').append($('metric-explorer'));
 $('metrics-owner').textContent=cohort?'CLASS PATTERNS':studentName().toUpperCase()+' / INDIVIDUAL RESULTS';
 $('metrics-title').textContent=cohort?'Understand the class, one dimension at a time':'Understand '+studentName()+'’s knowledge';
 $('metrics-scope-note').textContent=cohort?'Each student has equal weight. Structural values average individual graphs; they are not calculated on the combined class graph. Missing measurements are excluded and n is shown.':'Independent demonstrations define this student’s graph. The same reference version and communities are used for every student.';
 $('metrics-grid').replaceChildren();
 for(const [key,num,title,group,kind,prompt,definition] of METRIC_CARDS){
  const card=el('article',undefined,'analysis-card');card.dataset.metric=key;card.hidden=metricFilter!=='all'&&metricFilter!==group;
  card.append(el('p',num+' / '+group,'eyebrow'),el('h3',title),el('p',prompt,'metric-question'));
  card.append(el('strong',metricFormat(read(key),kind),'analysis-value'));
  if(kind==='percent'&&read(key)!=null)card.append(coverageBar(read(key),title));
  let detail='';
  if(key==='concept_reach')detail='Mean concept completeness: '+metricFormat(read('concept_completeness'),'percent');
  if(key==='components')detail='Largest-component share: '+metricFormat(read('largest_component'),'percent');
  if(key==='modularity')detail=a.reference.community_count+' fixed reference communities';
  if(key==='cross_topic_coverage')detail=a.reference.bridge_total+' reference bridge relationships'+(!a.reference.bridge_total?' · Not applicable in this scope':'');
  if(key==='connection_strength')detail='Normalized completeness: '+metricFormat(read('concept_completeness'),'percent');
  if(detail)card.append(el('p',detail,'metric-detail'));
  if(cohort){const stat=a.averages[key];card.append(el('small','Mean · n = '+stat.n+' / '+a.students+' students'));if(stat.n)card.append(el('small','Median '+metricFormat(stat.median,kind)+' · range '+metricFormat(stat.low,kind)+'–'+metricFormat(stat.high,kind)));}
  else if(key==='relationship_coverage'||key==='assessment_coverage')card.append(el('small',(key==='relationship_coverage'?profile.known:profile.assessed)+' / '+profile.total+' reference relationships'));
  else if(key==='concept_reach')card.append(el('small',profile.reached+' / '+profile.nodes+' reference concepts'));
  if(['average_degree','density','components','clustering','global_efficiency','modularity','concentration'].includes(key))card.append(el('small','Reference graph: '+metricFormat(a.reference.values[key],kind),'reference-value'));
  const more=el('details'),summary=el('summary','How to read this');more.append(summary,el('p',definition));card.append(more);$('metrics-grid').append(card);
 }
 for(const b of $('metric-filters').querySelectorAll('button'))b.setAttribute('aria-pressed',String(b.dataset.filter===metricFilter));
 $('metric-result-count').textContent=(metricFilter==='all'?12:METRIC_CARDS.filter(c=>c[3]===metricFilter).length)+' of 12 metrics';
 $('class-collective').hidden=!cohort;
 $('class-collective').replaceChildren(el('h3','Shared understanding vs. collective reach'),el('p','A path in the combined class graph may join facts known by different students. It does not prove any one student knows the whole path.'),
  metric(metricFormat(a.shared_coverage,'percent'),'Shared core',`Relationships known by at least ${100*a.shared_knowledge_fraction}% of the full roster.`),metric(metricFormat(a.collective_coverage,'percent'),'Collective coverage','Relationships known by at least one student.'));
 renderConceptMetrics();renderDegreeDistribution();
}
function renderConceptMetrics(){
 const a=S.scope.analytics;if(!a)return;const cohort=!S.detail||!S.scope.selected;
 $('concept-table-caption').textContent=cohort?'Class concept profile · degree and strength average each student; reference degree describes the course graph.':'Individual concept profile · incoming and outgoing degrees preserve direction. Completeness counts distinct reference facts.';
 const query=$('concept-search').value.toLowerCase(),sort=$('concept-sort').value;
 let rows=(cohort?a.concepts:S.scope.selected.graph_metrics.concepts).filter(c=>c.label.toLowerCase().includes(query));
 const sortValue=c=>sort==='completeness'?c.completeness:sort==='strength'?(cohort?c.strength:c.known):(cohort?c.mean_degree:c.degree);
 rows=[...rows].sort((a,b)=>(sortValue(b)??-1)-(sortValue(a)??-1)||a.label.localeCompare(b.label));
 const headers=cohort?['Concept / community','Mean degree','Reference degree','Mean strength','Completeness','Students assessed']:['Concept / community','Degree','In / out','Known / reference facts','Completeness','Facts assessed'];
 $('concept-table').replaceChildren(analyticsTable(headers,rows.map(c=>{const name=el('span',c.label);name.append(el('small',c.community));return cohort?[name,metricFormat(c.mean_degree),c.degree,metricFormat(c.strength),metricFormat(c.completeness,'percent'),c.assessed_students+' / '+a.students]:[name,c.degree,c.in_degree+' / '+c.out_degree,c.known+' / '+c.total,metricFormat(c.completeness,'percent'),c.assessed+' / '+c.total];})));
 if(!rows.length)$('concept-table').append(el('p',query?'No matching concepts.':'No reference concepts in this scope.','empty-state'));
}
function renderDegreeDistribution(){
 const cohort=!S.detail||!S.scope.selected,counts=new Map();
 const profiles=cohort?S.scope.students.map(r=>r.graph_metrics):[S.scope.selected.graph_metrics];
 profiles.forEach(p=>p.degree_distribution.forEach(r=>counts.set(r.degree,(counts.get(r.degree)||0)+r.concepts)));
 const target=$('degree-distribution');target.replaceChildren(el('h3','Degree distribution'),el('p',cohort?'Each bar counts demonstrated student–concept pairs with that many neighbors. A concept can appear once per student.':'Each bar counts demonstrated concepts with that many distinct neighbors. Unassessed concepts are excluded.'));
 if(!counts.size){target.append(el('p','No independently demonstrated concepts yet.','empty-state'));return;}
 const max=Math.max(...counts.values());for(const [degree,count] of [...counts].sort((a,b)=>a[0]-b[0])){const row=el('div',undefined,'degree-row'),bar=el('span',undefined,'degree-bar');bar.style.width=(count/max*100)+'%';const track=el('div',undefined,'degree-track');track.append(bar);row.append(el('span',degree+' neighbors'),track,el('strong',String(count)));target.append(row);}
}
function renderStudentEvidence(){
 const row=S.scope.selected;if(!row)return;const facts=row.knowledge,names=Object.fromEntries(S.scope.graph.nodes.map(n=>[n.id,n.label]));
 const buckets=[['student-strengths','Independent strengths',e=>facts[e.id]?.mark==='match'&&!facts[e.id]?.helped,'positive'],['student-support','Observed need for support',e=>facts[e.id]&&(facts[e.id].mark!=='match'||facts[e.id].helped),'support'],['student-unassessed','Still to assess',e=>!facts[e.id],'neutral']];
 for(const [id,title,select,tone] of buckets){const selected=S.scope.graph.edges.filter(select),host=$(id);host.className='evidence-card '+tone;host.replaceChildren(el('p',selected.length+' relationships','eyebrow'),el('h3',title));const list=el('ul');for(const e of selected.slice(0,APP_UI_SETTINGS.professor_summary_items)){const item=el('li',names[e.source]+' → '+e.label+' → '+names[e.target]);if(id==='student-support')item.append(el('small',facts[e.id].helped?'Assisted · '+(marks[facts[e.id].mark]||facts[e.id].mark):marks[facts[e.id].mark]));list.append(item);}host.append(selected.length?list:el('p',id==='student-unassessed'?'All relationships have resolved evidence.':'No evidence in this category yet.'));if(selected.length>APP_UI_SETTINGS.professor_summary_items)host.append(el('small','Showing '+APP_UI_SETTINGS.professor_summary_items+' of '+selected.length+'; explore the graph for all relationships.'));}
}
function renderClassNavigation(){
 const detail=S.detail&&Boolean(S.scope.selected);
 $('class-location').textContent=detail?'Class Overview / '+studentName():'Class Overview / All students';
 $('class-student-switch').replaceChildren(option('Class overview',''),...S.scope.students.map(r=>option(r.name,r.id)));$('class-student-switch').value=detail?S.student:'';
 $('class-jump-links').replaceChildren();
 const targets=detail?[['Student summary','student-title'],['12 metrics','metric-explorer'],['Concept details','concept-details'],['Learning graph','student-graph-host'],['Quiz history','history-area']]:[['Class summary','class-summary-view'],['12 metrics','metric-explorer'],['Students','roster-section'],['Class graph','class-graph-host']];
 for(const [label,id] of targets){const link=el('a',label);link.href='#'+id;link.onclick=()=>{if($(id).tagName==='DETAILS')$(id).open=true;};$('class-jump-links').append(link);}
 const rows=S.scope.students.map(r=>{const name=el('button',r.name,'text-button');name.onclick=()=>task(()=>openLearner(r.id));return [name,pct(r.metrics.knowledge_coverage),pct(r.metrics.assessment_coverage),metricFormat(r.graph_metrics.values.average_degree),metricFormat(r.graph_metrics.values.largest_component,'percent'),r.categories.unassessed];});
 $('student-comparison').replaceChildren(analyticsTable(['Student','Known','Checked','Average degree','Largest component','Unassessed facts'],rows));
}
$('class-student-switch').onchange=()=>task(async()=>{const id=$('class-student-switch').value;if(id)await openLearner(id);else{S.detail=false;S.review=null;persist();render();await renderGraph();}});
$('metric-filters').querySelectorAll('button').forEach(button=>button.onclick=()=>{metricFilter=button.dataset.filter;renderMetricExplorer();});
$('concept-search').oninput=renderConceptMetrics;
$('concept-sort').onchange=renderConceptMetrics;

function renderInsights(){
 const old=S.insight;S.insight=S.scope.runs.some(r=>r.id===old)?old:S.scope.runs[0]?.id||'';
 $('insight-run').replaceChildren(...S.scope.runs.map(r=>option(runLabel(r.id),r.id)));$('insight-run').value=S.insight;
 $('aggregate-source-control').hidden=Boolean(S.topic);$('insight-aggregate').checked=S.aggregate;
 $('insight-summary').replaceChildren(metric(S.scope.runs.length,'Included source runs','One selected version per input topic.'),metric(S.scope.graph.nodes.length,'Distinct recorded concepts','Endpoint label, definition and kind determine identity.'),metric(S.scope.unique_relationships,'Unique relationships',S.scope.source_relationships+' source occurrences; exact overlaps counted once.'));
 const table=el('table'),body=el('tbody');for(const r of S.scope.runs){const tr=el('tr'),button=el('button','Inspect','secondary');button.onclick=()=>task(async()=>{S.insight=r.id;S.aggregate=false;renderInsights();await renderGraph();await runResults();});const action=el('td');action.append(button);tr.append(el('td',r.title),el('td',r.run_name+' · '+r.status),el('td',r.relationships+' source relationships'),action);body.append(tr);}table.append(body);$('insight-breakdown').replaceChildren(table);persist();
}
let graphMessage=null;
async function renderGraph(){
 if(!S.scope)return;const generation=S.generation,scope=S.scope;
 const isInsight=S.tab==='insights',isClass=S.tab==='class'&&!S.detail;
 const host=isInsight?'insight-graph-host':S.tab==='quiz'?'quiz-graph-host':S.detail?'student-graph-host':'class-graph-host';$(host).append($('graph-workspace'));
 let run=isInsight?(S.topic||!S.aggregate?S.insight:null):S.topic?scope.runs[0]?.id:null;
 if(S.tab==='quiz'&&activeInScope()&&!S.active.state.completed)run=S.active.run_id;
 let mode=isInsight?'explore':isClass?'class':S.tab==='class'?'knowledge':S.graphMode;if(mode==='knowledge'&&!S.student)mode='explore';
 if(S.tab==='quiz'&&activeInScope()&&!S.active.state.completed)mode='knowledge';
 $('graph-mode').value=mode;$('graph-mode').hidden=isInsight||S.tab==='class';document.querySelector('label[for="graph-mode"]').hidden=isInsight||S.tab==='class';$('graph-title').textContent=isInsight?(originalRun===run?'Original generated graph':'Current source graph'):isClass?'Class learning graph':studentName()+' — learning graph';
 $('graph-context').textContent=run?runLabel(run):scope.runs.map(r=>r.title+' / '+r.run_name+' / '+r.id.slice(0,APP_UI_SETTINGS.run_id_chars)).join(' · ');
 $('graph-help').textContent=run?'Select circles or arrows for definitions and evidence. Explore / compare statements enables temporary model matching; it never writes student grades.':'Combined graph of the included source versions. Exact overlaps count once. Select an arrow to inspect every source. Open one topic for statement comparison; quizzes always use one source graph.';
 $('compare-source').hidden=Boolean(run)||!$('quiz-source').value;
 const legends=mode==='explore'?[['#69aeff','Document'],['#f5ae68','Background'],['#bf9bff','Manual'],['#f472b6','Student contributions']]:mode==='class'?[['#54d99a','Brighter / thicker: more independently know'],['#62738d','Unassessed or no roster proportion']]:[['#54d99a','Independent'],['#f3bf62','Partial or assisted'],['#ff7e8b','Incorrect / not demonstrated'],['#62738d','Unassessed']];
 if(mode!=='explore')legends.push(['#f472b6','Pink outline: student contribution']);
 $('graph-legend').replaceChildren(...legends.map(([color,text])=>{const n=el('span',text);n.style.setProperty('--key-color',color);return n;}));
 graphMessage=null;let url;
 if(!scope.runs.length){$('graph').removeAttribute('src');$('graph').hidden=true;$('overlay-counts').replaceChildren(el('p','No graphs available.'));return;}$('graph').hidden=false;
 if(run){const report=await api('runs/'+run+'/knowledge'+(S.student?'?student_id='+S.student:''));if(generation!==S.generation)return;graphMessage={type:'professor-coverage',state:mode==='knowledge'?(S.tab==='quiz'&&activeInScope()&&!S.active.state.completed&&!S.active.graph_review?.changed?S.active.state:report.state):null,overlay:mode==='class'?report.overlay:null};url='/professor/graph/'+run+'?embedded=true&revision='+S.generation+(isInsight&&originalRun===run?'&version=original':'');if(isInsight&&originalRun===run)graphMessage=null;const nodes=Object.fromEntries(report.graph.nodes.map(n=>[n.id,n.label]));$('overlay-counts').replaceChildren(...report.overlay.map(r=>el('p',nodes[r.source]+' → '+r.label+' → '+nodes[r.target]+' · '+r.known+'/'+r.students+' independently know; '+r.assessed+' assessed · '+evidenceLabel(report.knowledge[r.id])+' · source '+runLabel(run))));}
 else{const p=scopeParams(mode==='knowledge');p.set('mode',mode==='knowledge'?'student':mode==='class'?'class':'source');p.set('revision',S.generation);url='/professor/scope-graph?'+p;const nodes=Object.fromEntries(scope.graph.nodes.map(n=>[n.id,n.label]));$('overlay-counts').replaceChildren(...scope.overlay.map(r=>el('p',nodes[r.source]+' → '+r.label+' → '+nodes[r.target]+' · '+r.known+'/'+r.students+' independently know; '+r.assessed+' assessed · sources: '+r.sources.map(s=>s.topic+' / '+s.run_name).join('; '))));}
 if(isInsight&&originalRun===run){$('overlay-counts').replaceChildren(el('p','Original generated graph. Current learning metrics use the edited version.'));$('graph-help').textContent='Read-only comparison with the untouched generated graph. Use View edited graph to return to your saved edits.';}
 if($('graph').getAttribute('src')!==url)$('graph').src=url;else postGraph();controls();
 if($('learning-details').open&&S.tab!=='insights')await learningDetails();
}
async function learningDetails(){
 const cohort=S.tab==='class'&&!S.detail, m=cohort?S.scope.averages:S.scope.selected?.metrics;
 const fields=[['independent_score','Independent answer score',true],['assisted_score','Assisted answer score',true],['connected_understanding','Connected understanding',true],['mastered_components','Mastered components',false],['isolated_mastered_concepts','Isolated mastered concepts',false],['concentration','Topic concentration (HHI)',false]];
 $('advanced-learning-metrics').replaceChildren(...fields.map(([k,label,percent])=>{const v=cohort?m?.[k]?.value:m?.[k];const n=cohort?'n = '+(m?.[k]?.n||0)+' students':k==='independent_score'?'n = '+(m?.independent_answers||0)+' questions':k==='assisted_score'?'n = '+(m?.assisted_answers||0)+' questions':'Current topic scope';return metric(percent?pct(v):value(v),label,n);}));
 const id=$('learning-source').value,generation=S.generation;
 if(!id){$('learning-source-details').replaceChildren(el('p','No source graphs available.'));return;}
 const report=await api('runs/'+id+'/knowledge'+(!cohort&&S.student?'?student_id='+S.student:''));
 if(generation!==S.generation||id!==$('learning-source').value)return;
 const target=$('learning-source-details');target.replaceChildren(el('p',runLabel(id),'source-context'));
 if(!cohort&&!S.student){target.append(el('p','Select a student to view their progress.'));return;}
 const selected=report.selected,progress=cohort?report.progress:selected?.progress||[],groups=cohort?report.topics:selected?.metrics.topics||[];
 target.append(el('h3','Progress on this source version'),el('p','Coverage uses all relationships in this source. Scores use latest answers per question. Corrections are reflected retrospectively; transferred knowledge appears as a baseline.'));
 const table=(headers,rows)=>{const t=el('table'),h=el('tr');headers.forEach(x=>h.append(el('th',x)));const head=el('thead');head.append(h);t.append(head);const body=el('tbody');rows.forEach(values=>{const row=el('tr');values.forEach(x=>row.append(el('td',x)));body.append(row);});t.append(body);const scroll=el('div',undefined,'table-scroll');scroll.append(t);return scroll;};
 if(progress.length){
 const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 600 130');svg.setAttribute('role','img');svg.setAttribute('aria-label','Progress from 0 to 100 percent, oldest to newest. Exact values are in the table below.');svg.style.maxHeight='170px';
 for(const[key,color]of [['knowledge_coverage','#54d99a'],['average_score','#69aeff']]){const points=progress.map((p,i)=>p[key]==null?null:[20+i*560/Math.max(1,progress.length-1),110-p[key]]).filter(Boolean);const line=document.createElementNS(ns,'polyline');line.setAttribute('points',points.map(p=>p.join(',')).join(' '));line.setAttribute('fill','none');line.setAttribute('stroke',color);line.setAttribute('stroke-width','2');svg.append(line);for(const[x,y]of points){const dot=document.createElementNS(ns,'circle');for(const[k,v]of Object.entries({cx:x,cy:y,r:3,fill:color}))dot.setAttribute(k,v);svg.append(dot);}}
 target.append(el('p','Green: independently known coverage. Blue: answer performance. Vertical scale: 0–100%; left to right: saved answer order.'),svg,table(['When / baseline','Known','Checked','Answer score'],progress.map(p=>[p.label||date(p.at),pct(p.knowledge_coverage),p.assessment_coverage==null?'Unavailable':pct(p.assessment_coverage),pct(p.average_score)])));
 }else target.append(el('p','No measured progress on this version yet.'));
 target.append(el('h3','Graph communities'),el('p','Groups of connected concepts within this source, distinct from input topics. Assessed score includes helped answers; known coverage requires independent answers.'),table(['Community','Known','Assessed / relationship opportunities','Assessed fact score'],groups.map(g=>[g.title,pct(g.knowledge_coverage),g.assessed+' / '+g.total,pct(g.assessed_score)])));
}
$('learning-details').addEventListener('toggle',()=>{if($('learning-details').open&&!S.busy)task(learningDetails);});
$('learning-source').onchange=()=>task(learningDetails);
function postGraph(){if(graphMessage)$('graph').contentWindow?.postMessage(graphMessage,location.origin);}
$('graph').addEventListener('load',postGraph);
window.addEventListener('message',event=>{if(event.origin===location.origin&&event.source===$('graph').contentWindow&&event.data?.type==='professor-graph-height'&&Number.isFinite(event.data.height))$('graph').style.height=Math.min(12000,Math.max(600,event.data.height))+'px';});
async function runResults(){
 const run=S.insight;if(!run)return;const data=await api('runs/'+run+'/results');if(S.insight!==run)return;
 $('results-meta').textContent=runLabel(run)+' · '+date(data.date)+' · '+data.status;
 $('run-cards').replaceChildren(...[[duration(data.duration),'Runtime'],[value(data.nodes),'Concepts'],[value(data.edges),'Relationships'],[value(data.accepted),'Background accepted'],[value(data.rejected),'Background rejected'],[value(data.unresolved),'Unresolved items']].map(([v,l])=>metric(v,l)));
 const v=data.validation||{};$('validation-cards').replaceChildren(...[['relations','Retained extracted relations'],['accepted','Accepted document relations'],['rejected','Rejected document relations'],['unresolved','Unresolved document reviews']].map(([k,l])=>metric(value(v[k]),l)));
 $('validation-details').textContent=JSON.stringify(data.validation_records||{available:false},null,2);
 $('reconstruction-scores').replaceChildren(metric(data.reconstruction_score==null?'Unavailable':data.reconstruction_score+' / 100','Document reconstruction','Pipeline fidelity estimate, not a student score or fact check.'));
 for(const[k,e]of Object.entries(data.scores||{})){if(k==='final_score')continue;$('reconstruction-scores').append(metric(value(typeof e==='object'?e?.mean:e),k.replaceAll('_',' '),e?.n!=null?'Chunk summary; n='+e.n:undefined));}
 $('score-definition').textContent=(data.interpretation||'No score interpretation recorded.')+' Metric version: '+value(data.metric_version)+'. Run-level quality is shown per source; no mixed-version aggregate score is invented.';
 $('original-text').textContent=data.original??'Unavailable';$('reconstructed-text').textContent=data.reconstructed??'Unavailable';
 $('run-steps').replaceChildren();$('step-chart').replaceChildren();for(const step of data.steps){const row=el('tr');for(const text of [step.name,step.status||'Unavailable',duration(step.duration),JSON.stringify(step.counts)])row.append(el('td',text));$('run-steps').append(row);}
 $('run-diagnostics').textContent=JSON.stringify({metric_version:data.metric_version,configuration:data.configuration,validation:data.validation},null,2);
 await backgroundFacts(run);
 await loadManualEditor();
}
async function backgroundFacts(run){
 const data=await api('runs/'+run+'/quiz-material');if(S.insight!==run)return;
 const box=$('background-facts');box.replaceChildren();
 if(!data.facts.length){box.append(el('p','This source version has no background or student-contributed facts to approve for quizzes.'));return;}
 for(const row of data.facts){
  const fact=row.fact,card=el('article',undefined,'answer-card'),form=el('form');
  card.append(el('h3',row.source_name+' — '+fact.label.replaceAll('_',' ')+' — '+row.target_name),
   el('p',fact.definition||'No definition recorded.'),el('p','Evidence: '+(typeof fact.evidence==='string'?fact.evidence:JSON.stringify(fact.evidence)||'Unavailable')),
   el('p',row.eligible?'Approved for quizzes. '+row.approval.reason:'Not approved; excluded from quizzes.'));
  const reason=el('textarea');reason.required=true;reason.maxLength=1500;reason.rows=2;reason.id='approval-'+fact.id;
  const label=el('label','Review reason or supporting reference');label.htmlFor=reason.id;
  const save=el('button',row.eligible?'Revoke quiz approval':'Approve for quizzes');save.type='submit';
  form.append(label,reason,save);form.onsubmit=e=>{e.preventDefault();task(async()=>{
   await api('runs/'+run+'/facts/'+encodeURIComponent(fact.id)+'/approval',{approved:!row.eligible,reason:reason.value});
   await backgroundFacts(run);
 await loadManualEditor();status('Quiz material review saved for this source version. Existing grades are retained.');
  });};card.append(form);box.append(card);
 }
}
async function chooseQuiz(){
 $('quiz-student').replaceChildren(...S.catalog.students.map(s=>option(s.name+' · '+s.id.slice(0,APP_UI_SETTINGS.student_id_chars),s.id)));$('quiz-student').value=S.student;$('quiz-student-note').textContent='Source: '+runLabel($('quiz-source').value)+'. Answers stay attached to this source version.';$('quiz-student-dialog').showModal();
}
async function command(action,prepared=null){
 let request=prepared||S.pending;S.failedQuestion=null;
 if(!request){request={action,request_id:crypto.randomUUID()};if(action==='start'){Object.assign(request,{student_id:$('quiz-student').value,run_id:$('quiz-source').value,focus_id:$('focus').value||null,review_mode:$('review-mode').checked,scope_all:!S.topic});}else{Object.assign(request,{session_id:S.active.id,question_id:S.active.state.question.id});if(action==='answer')request.text=$('answer').value.trim();}}
 S.pending=request;storage.set('pending',request);status('Preparing or assessing this question. Your saved work is retained.');
 let result;try{result=await api('quiz',request);}catch(error){if([400,404,422].includes(error.status)||error.code==='graph_changed'){S.pending=null;storage.set('pending',null);}if(error.code==='question_generation')S.failedQuestion=request;throw error;}S.pending=null;storage.set('pending',null);const changed=S.active?.state.question.id!==result.state.question.id;S.active=result;S.student=result.student_id;storage.set('active',{id:result.id,student_id:result.student_id});if(changed)$('answer').value='';fillSelectors();await loadScope();status(action==='hint'?'Hint saved. Later answers to this question count as assisted.':action==='reveal'?(result.state.question.help_source==='validated_expected_answer'?'Showing the saved validated answer. Later answers to this question count as assisted.':'Answer revealed. Later answers to this question count as assisted.'):'Assessment saved.');
 if(result.contribution_answer_id){
  status('Grade saved. Checking extra claims separately...');
  try{const data=await api('answers/'+result.contribution_answer_id+'/contributions/check',{});
   await loadScope();const job=data.jobs.find(j=>j.answer_id===result.contribution_answer_id);
   status(job?.status==='completed'?'Grade saved. Contribution review completed.':'Grade saved. Contribution review needs attention in Student contributions.');
  }catch(error){status('Grade saved. Contribution check can be retried in Student contributions: '+error.message,true);}
 }
}

async function resumeQuiz(id){
 const result=await api('sessions/'+id),r=source(result.run_id);if(!r)throw new Error('The saved source is not in the catalog; refresh runs.');
 S.student=result.student_id;S.topic=r.topic_key;S.runs[S.topic]=r.id;S.active=result;S.tab='quiz';S.review=null;
 if(result.pending_answers?.length){S.pending=result.pending_answers[0].request;storage.set('pending',S.pending);$('answer').value=S.pending.text;}
 else if(S.pending?.session_id===id){S.pending=null;storage.set('pending',null);}
 storage.set('active',{id:result.id,student_id:result.student_id});fillSelectors();await loadScope();status('Resumed on its original source version: '+runLabel(r.id));$('assessment-area').scrollIntoView();
}
async function review(id){
 const data=await api('sessions/'+id);S.review=id;$('review').hidden=false;$('review-meta').textContent=studentName(data.student_id)+' · '+runLabel(data.run_id)+' · '+date(data.created_at);$('answers').replaceChildren();
 for(const answer of data.answers){const card=el('article',undefined,'answer-card');card.append(el('h3','Question '+answer.question.number+': '+answer.question.text),el('p',answer.text,'answer-text'),el('p','Current score: '+pct(answer.score)+' · original: '+pct(answer.original_score)+' · '+(answer.helped?'Assisted':'Independent')),el('p',answer.effective_feedback));if(answer.graph_changes?.length)card.append(el('p','Graph meaning changed or removed: '+answer.graph_changes.join(', ')+'. Historical grade retained; this evidence does not award mastery of the changed meaning.','notice'));const evidence=el('details');evidence.append(el('summary','Expected answer and grading evidence'),el('p',answer.question.expected_answer),el('pre',JSON.stringify(answer.result,null,2)));card.append(evidence);
 if(answer.result.assessment_spec){card.append(el('p','Assessed scope: '+answer.result.assessment_spec.map(c=>c.scope==='component'?'Part of a relationship: '+c.requested:'Full relationship: '+c.requested).join('; ')),el('p','A correct component answer can earn 100% on this question while the relationship remains yellow. Green requires an independent full-relationship demonstration.'));}
 if(answer.result.graph_assessment?.status==='unresolved'){
  card.append(el('p','Graph matching unresolved. The question grade is saved; relationship progress was unchanged.'));
  const retry=el('button','Retry graph matching','secondary');retry.onclick=()=>task(async()=>{
   const outcome=await api('answers/'+answer.id+'/retry-matching',{});
   if(S.active?.id===id)S.active=await api('sessions/'+id);
   await loadScope();await review(id);status(outcome.status==='resolved'?'Graph matching completed. The original question grade is unchanged.':'Graph matching remains unresolved. The answer and grade are retained.',outcome.status!=='resolved');
  });card.append(retry);
 }
 if(answer.overrides.length){const audit=el('details');audit.append(el('summary','Correction history'));for(const row of answer.overrides)audit.append(el('p',date(row.created_at)+' · '+row.reason+' · '+row.feedback));card.append(audit);}
 if(answer.question.examiner_material.facts.length){const form=el('form',undefined,'override'),selects={};form.append(el('h3','Correct grading'),el('p','Corrections apply to the assessed scope. A component question cannot award full-relationship mastery. For a full-relationship question, a correct override explicitly confirms that demonstration.'));
 for(const fact of answer.question.examiner_material.facts){const row=el('div',undefined,'rubric'),select=el('select');select.id='grade-'+answer.id+'-'+Object.keys(selects).length;const label=el('label',fact.source+' '+fact.relation.replaceAll('_',' ')+' '+fact.target);label.htmlFor=select.id;select.append(...Object.entries(marks).map(([k,v])=>option(v,k)));select.value=answer.effective_marks[fact.id];selects[fact.id]=select;row.append(label,select);form.append(row);}
 const feedback=el('textarea'),reason=el('textarea');feedback.id='feedback-'+answer.id;reason.id='reason-'+answer.id;feedback.required=reason.required=true;feedback.maxLength=3000;reason.maxLength=1500;feedback.rows=reason.rows=2;feedback.value=answer.effective_feedback;const fl=el('label','Feedback for the student');fl.htmlFor=feedback.id;const rl=el('label','Reason for this correction');rl.htmlFor=reason.id;const save=el('button','Save correction');save.type='submit';form.append(fl,feedback,rl,reason,save);form.onsubmit=e=>{e.preventDefault();task(async()=>{await api('answers/'+answer.id+'/override',{marks:Object.fromEntries(Object.entries(selects).map(([k,v])=>[k,v.value])),feedback:feedback.value,reason:reason.value});if(S.active?.id===id)S.active=await api('sessions/'+id);await loadScope();await review(id);status('Correction saved. Original grading and history retained.');});};card.append(form);}else card.append(el('p','No factual rubric; unscored.'));$('answers').append(card);}
 for(const pending of data.pending_answers||[]){const card=el('article',undefined,'answer-card');card.append(el('h3','Saved answer — '+pending.grading_status),el('p',pending.text),el('p','No score assigned; mastery unchanged.'),el('p',pending.error||'Awaiting grading.'));const retry=el('button','Resume and retry saved answer','secondary');retry.onclick=()=>task(async()=>{await resume(id);await command('answer',pending.request);});card.append(retry);$('answers').append(card);}
 if(!data.answers.length&&!data.pending_answers?.length)$('answers').append(el('p','No graded answers yet. Quiz state is retained.'));
 $('review').scrollIntoView();
}
for(const button of document.querySelectorAll('[data-tab]'))button.onclick=()=>task(()=>showTab(button.dataset.tab));
$('scope-topic').onchange=()=>task(async()=>{S.failedQuestion=null;S.topic=$('scope-topic').value;S.review=null;$('review').hidden=true;fillSelectors();await loadScope();});
$('topic').onchange=()=>task(async()=>{S.failedQuestion=null;S.runs[S.topic]=$('topic').value;S.review=null;$('review').hidden=true;persist();await loadScope();});
$('student-select').onchange=()=>task(async()=>{S.failedQuestion=null;S.student=$('student-select').value;fillSelectors();await loadScope();});
$('quiz-source').onchange=()=>{fillFocus();controls();};
$('review-mode').onchange=controls;
$('insight-run').onchange=()=>task(async()=>{S.insight=$('insight-run').value;S.aggregate=false;persist();renderInsights();await renderGraph();await runResults();});
$('insight-aggregate').onchange=()=>task(async()=>{S.aggregate=$('insight-aggregate').checked;await renderGraph();});
$('graph-mode').onchange=()=>task(async()=>{S.graphMode=$('graph-mode').value;await renderGraph();});
$('compare-source').onclick=()=>task(()=>openSource($('quiz-source').value));
$('refresh').onclick=()=>task(async()=>{await refresh();status('Saved runs refreshed. No extraction was run.');});
$('student-search').oninput=renderClass;
$('back-to-class').onclick=()=>task(async()=>{S.detail=false;S.review=null;$('review').hidden=true;persist();render();await renderGraph();});
$('quiz-this-student').onclick=()=>task(()=>showTab('quiz'));
$('student-form').onsubmit=e=>{e.preventDefault();task(async()=>{const s=await api('students',{name:$('student-name').value});S.student=s.id;$('student-name').value='';await refresh();status('Student added.');});};
$('try-another-concept').onclick=()=>task(async()=>{
 const request={...S.failedQuestion,request_id:crypto.randomUUID()},r=source(request.run_id||S.active?.run_id);
 const previous=request.focus_id||$('focus').value,concepts=r?.concepts||[];
 if(!concepts.length)throw new Error('Choose another topic before starting a quiz.');
 request.focus_id=concepts[(concepts.findIndex(n=>n.id===previous)+1)%concepts.length].id;
 $('focus').value=request.focus_id;
 await command(request.action,request);
});
$('start').onclick=()=>task(chooseQuiz);
$('cancel-quiz-student').onclick=()=>$('quiz-student-dialog').close();
$('quiz-student-form').onsubmit=e=>{e.preventDefault();$('quiz-student-dialog').close();task(()=>command('start'));};
$('answer-form').onsubmit=e=>{e.preventDefault();task(()=>command('answer'));};
for(const action of ['hint','reveal','next'])$(action).onclick=()=>task(()=>command(action));
$('retry').onclick=()=>task(()=>command(S.pending.action));
$('close-review').onclick=()=>{S.review=null;$('review').hidden=true;};
$('open-pending').onclick=()=>task(async()=>{if(S.pending.session_id)await resumeQuiz(S.pending.session_id);else{const r=source(S.pending.run_id);S.student=S.pending.student_id;S.topic=r.topic_key;S.runs[S.topic]=r.id;S.tab='quiz';fillSelectors();await loadScope();await command('start');}});
let manualState=null, originalRun=null;
const relationshipFields=['label','definition','conditions','modality','purpose','timing','evidence'];
function manualControls(){
 const available=Boolean(manualState&&manualState.run_id===S.insight), original=originalRun===S.insight;
 $('delete-concept').disabled=S.busy||!available||!$('edit-concept').value||original;
 $('delete-relationship').disabled=S.busy||!available||!$('edit-relationship').value||original;
 $('save-concept').disabled=S.busy||!available||original;
 $('save-relationship').disabled=S.busy||!available||!manualState.graph.nodes.length||original;
}
function conceptFields(){
 const row=manualState?.graph.nodes.find(n=>n.id===$('edit-concept').value);
 $('concept-label').value=row?.label||'';$('concept-definition').value=row?.definition||'';
 $('save-concept').textContent=row?'Save concept':'Add concept';manualControls();
}
function participantRow(value={}){
 const row=el('div',undefined,'manual-participant'),id=crypto.randomUUID();
 const node=el('select'),role=el('input'),scope=el('select'),remove=el('button','Remove participant','secondary');
 node.dataset.field='node';role.dataset.field='role';scope.dataset.field='scope';role.maxLength=200;role.required=true;
 node.append(...manualState.graph.nodes.map(n=>option(n.label,n.id)));node.value=value.node||manualState.graph.nodes[0]?.id||'';
 scope.append(...['source','target','assertion','purpose'].map(s=>option(s,s)));scope.value=value.scope||'assertion';role.value=value.role||'';
 for(const [field,label] of [[node,'Participant concept'],[role,'Role'],[scope,'Scope']]){field.id='participant-'+id+'-'+field.dataset.field;const l=el('label',label);l.htmlFor=field.id;row.append(l,field);}
 remove.type='button';remove.onclick=()=>row.remove();row.append(remove);$('relationship-participants').append(row);
}
function relationshipFieldsFill(){
 const row=manualState?.graph.edges.find(e=>e.id===$('edit-relationship').value);
 for(const field of relationshipFields)$('relationship-'+field).value=typeof row?.[field]==='string'?row[field]:'';
 for(const field of ['source','target']){const select=$('relationship-'+field);select.replaceChildren(...manualState.graph.nodes.map(n=>option(n.label,n.id)));select.value=row?.[field]||manualState.graph.nodes[field==='source'?0:Math.min(1,manualState.graph.nodes.length-1)]?.id||'';}
 $('relationship-participants').replaceChildren();for(const participant of row?.participants||[])participantRow(participant);
 $('save-relationship').textContent=row?'Save relationship':'Add relationship';manualControls();
}
async function loadManualEditor(){
 const run=S.insight;$('manual-editor').hidden=!run;if(!run)return;
 const data=await api('runs/'+run+'/manual-graph');if(run!==S.insight)return;
 manualState=data;
 $('professor-identity').value=storage.get('professor-identity')||'';
 $('manual-context').textContent=runLabel(run)+' · '+data.graph.nodes.length+' concepts · '+data.graph.edges.length+' relationships · '+(data.edited?'Manual version':'Generated version')+' · revision '+data.revision;
 $('view-original').hidden=!data.changes.length;
 $('view-original').textContent=originalRun===run?'View edited graph':'View original graph';
 $('manual-forms').hidden=originalRun===run;
 $('manual-impact').hidden=!data.affected_assessments.length;
 $('manual-impact').textContent=data.affected_assessments.length+' historical answers reference changed or deleted relationships. Their grades are preserved; obsolete evidence does not count as current mastery. New evidence is needed for the changed meaning.';
 $('edit-concept').replaceChildren(option('Add a new concept',''),...data.graph.nodes.map(n=>option(n.label,n.id)));
 const names=Object.fromEntries(data.graph.nodes.map(n=>[n.id,n.label]));
 $('edit-relationship').replaceChildren(option('Add a new relationship',''),...data.graph.edges.map(e=>option(names[e.source]+' → '+e.label+' → '+names[e.target],e.id)));
 conceptFields();relationshipFieldsFill();
 const list=$('manual-change-list');list.replaceChildren();
 for(const change of [...data.changes].reverse()){
  const article=el('article',undefined,'answer-card');article.append(el('h4','Change '+change.revision+' · '+change.action+(change.reverts?' change '+change.reverts:'')),el('p',date(change.timestamp)+' · '+(change.professor?change.professor.name+' ('+change.professor.source.replace('_',' ')+')':'Professor identity unavailable')));
  if(change.reason)article.append(el('p',change.reason));
  for(const item of change.items){const details=el('details'),summary=el('summary',item.action+' '+item.entity+': '+(item.after?.label||item.before?.label||item.id));details.append(summary,el('p','ID: '+item.id));const columns=el('div',undefined,'text-comparison');for(const side of ['before','after']){const block=el('div');block.append(el('h4',side==='before'?'Before':'After'),el('pre',JSON.stringify(item[side],null,2)));columns.append(block);}details.append(columns);article.append(details);}
  if(change.affected_relationships.length)article.append(el('p','Meaning changed or removed for '+change.affected_relationships.length+' relationships.'));
  const revert=el('button','Revert change '+change.revision,'secondary');revert.onclick=()=>task(()=>saveManual({action:'revert',change_revision:change.revision}));article.append(revert);list.append(article);
 }
 if(!data.changes.length)list.append(el('p','No manual changes. The generated graph is untouched.'));
 manualControls();
}
async function saveManual(command){
 const run=manualState.run_id,professor=$('professor-identity').value.trim();storage.set('professor-identity',professor);
 await api('runs/'+run+'/manual-graph',{...command,revision:manualState.revision,request_id:crypto.randomUUID(),professor:professor||null,reason:$('manual-reason').value});
 originalRun=null;S.aggregate=false;$('manual-reason').value='';
 if(S.active)S.active=await api('sessions/'+S.active.id);
 await refresh();status('Manual graph change saved for this run. Original graph and assessment history retained.');
}
$('edit-concept').onchange=conceptFields;
$('edit-relationship').onchange=relationshipFieldsFill;
$('add-participant').onclick=()=>participantRow();
$('concept-form').onsubmit=e=>{e.preventDefault();task(()=>saveManual({action:$('edit-concept').value?'edit':'add',entity:'concept',id:$('edit-concept').value||null,values:{label:$('concept-label').value,definition:$('concept-definition').value}}));};
$('relationship-form').onsubmit=e=>{e.preventDefault();task(()=>{
 const values=Object.fromEntries([...relationshipFields,'source','target'].map(k=>[k,$('relationship-'+k).value]));
 values.participants=[...$('relationship-participants').children].map(row=>Object.fromEntries([...row.querySelectorAll('[data-field]')].map(field=>[field.dataset.field,field.value])));
 // Preserve untouched optional fields, including original null/missing values.
 const existing=manualState.graph.edges.find(r=>r.id===$('edit-relationship').value);
 if(existing)for(const k of Object.keys(values)){if(k==='participants'?JSON.stringify(existing[k]||[])===JSON.stringify(values[k]):(existing[k]||'')===values[k])delete values[k];}
 return saveManual({action:existing?'edit':'add',entity:'relationship',id:existing?.id||null,values});
});};
for(const kind of ['concept','relationship'])$('delete-'+kind).onclick=()=>task(async()=>{
 const id=$('edit-'+kind).value;if(!id)return;
 const attached=kind==='concept'?manualState.graph.edges.filter(e=>e.source===id||e.target===id||e.participants?.some(p=>p.node===id)).length:0;
 if(!confirm('Delete this '+kind+(attached?' and its '+attached+' connected relationships':'')+'? This action can be reverted from manual changes.'))return;
 await saveManual({action:'delete',entity:kind,id});
});
$('view-original').onclick=()=>task(async()=>{originalRun=originalRun===S.insight?null:S.insight;S.aggregate=false;await loadManualEditor();await renderGraph();status(originalRun?'Viewing the untouched original. Manual edits remain saved.':'Viewing the saved edited graph.');});
$('view-manual-changes').onclick=()=>{$('manual-history').hidden=!$('manual-history').hidden;$('view-manual-changes').setAttribute('aria-expanded',String(!$('manual-history').hidden));};
$('reload-manual').onclick=()=>task(async()=>{await refresh();status('Loaded the latest saved graph and manual changes.');});

task(async()=>{S.catalog=await api('catalog');const params=new URLSearchParams(location.search),requested=params.get('run');if(['quiz','class','insights'].includes(params.get('view'))){S.tab=params.get('view');S.detail=false;}if(requested&&source(requested)){const r=source(requested);S.topic=r.topic_key;S.runs[S.topic]=r.id;}const active=storage.get('active');if(active){try{S.active=await api('sessions/'+active.id);if(S.active.pending_answers?.length&&!S.pending){S.pending=S.active.pending_answers[0].request;storage.set('pending',S.pending);}}catch(e){if(e.status===404){if(S.pending?.session_id===active.id){S.pending=null;storage.set('pending',null);}S.active=null;storage.set('active',null);status('The previous quiz is no longer in the saved records. Select a student to begin.');}else status('Saved quiz could not be restored: '+e.message,true);}}await refresh();if(S.pending?.text)$('answer').value=S.pending.text;});

async function loadContributions(){
 const generation=S.generation, box=$('contribution-list');
 const results=await Promise.all((S.scope?.runs||[]).map(r=>api('runs/'+r.id+'/contributions')));
 if(generation!==S.generation)return;
 box.replaceChildren();let count=0;
 for(const data of results){
  for(const job of data.jobs.filter(j=>j.status!=='completed')){
   const card=el('article',undefined,'answer-card');
   card.append(el('p',runLabel(data.run_id)+' · Answer '+job.answer_id+' · '+job.status),el('p',job.error||'Contribution check pending. The grade is already saved.'));
   const retry=el('button','Check extra claims','secondary');retry.onclick=()=>task(async()=>{status('Checking extra claims; the saved grade is unchanged.');await api('answers/'+job.answer_id+'/contributions/check',{});await loadScope();status('Contribution check saved.');});card.append(retry);box.append(card);count++;
  }
  for(const row of data.contributions){
   const card=el('article',undefined,'answer-card contribution-card');card.dataset.contributionId=row.id;
   card.append(el('h3',row.student_name+' · '+(row.status==='accepted'&&!row.published?'removed from graph':row.status.replaceAll('_',' '))),el('p',row.claim.statement),el('p','Student quote: '+row.claim.quote),el('small',runLabel(row.run_id)+' · Answer '+row.answer_id));
   const history=el('button','Open quiz and answer','secondary');history.onclick=()=>task(async()=>{S.student=row.student_id;await openSource(row.run_id,'quiz');await review(row.session_id);});card.append(history);
   const details=el('details');details.append(el('summary','Validation evidence and attribution'),el('pre',JSON.stringify(row,null,2)));card.append(details);
   if(row.publication_error)card.append(el('p',row.publication_error));
   const actions=row.status==='accepted'&&row.published?['undo']:row.status==='needs_review'?['approve','reject']:[];
   if(actions.length){const form=el('form',undefined,'contribution-review'),name=el('input'),reason=el('textarea');
    name.required=reason.required=true;name.maxLength=200;reason.maxLength=1500;name.placeholder='Professor name';reason.placeholder='Review reason';name.setAttribute('aria-label','Professor name');reason.setAttribute('aria-label','Review reason');
    form.append(name,reason);for(const action of actions){const button=el('button',action==='undo'?'Undo graph addition':action==='approve'?'Approve graph addition':'Reject claim');button.type='submit';button.value=action;form.append(button);}
    form.onsubmit=event=>{event.preventDefault();const action=event.submitter.value;task(async()=>{await api('contributions/'+row.id+'/review',{action,professor:name.value,reason:reason.value});await loadScope();status('Contribution review saved. Quiz grades are unchanged.');});};card.append(form);
   }
   box.append(card);count++;
  }
 }
 if(!count)box.append(el('p','No extra claims have been submitted in this scope.'));
}
