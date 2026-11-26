from pathlib import Path
root=Path(__file__).parent
def edit(name, old, new):
    path=root/name
    text=path.read_text(encoding='utf-8')
    if old not in text and new in text: return
    assert old in text, (name,old[:100])
    path.write_text(text.replace(old,new),encoding='utf-8')

edit('pipeline.assessment.py', "fact.get('origin') != 'background'", "fact.get('origin') not in {'background', 'student'}")
edit('pipeline.student_store.py', "fact.get('origin')!='background'", "fact.get('origin') not in {'background', 'student'}")
edit('pipeline.student_store.py', 'Select a background fact', 'Select a background or student-contributed fact')
edit('pipeline.professor.py', "e.get('origin')!='background'", "e.get('origin') not in {'background', 'student'}")
edit('pipeline.professor.py', "e.get('origin')=='background'", "e.get('origin') in {'background', 'student'}")
edit('professor.js', 'This source version has no generated background facts.', 'This source version has no background or student-contributed facts to approve for quizzes.')
edit('graph_view.html', "manual:'#bf9bff'", "manual:'#bf9bff',student:'#f472b6'")
edit('graph_view.html', "['document','background','manual']", "['document','background','manual','student']")
edit('graph_view.html', "for(const origin of ['document'", "const studentArrow=manualArrow.cloneNode(true);studentArrow.id='arrow-student';manualArrow.parentNode.append(studentArrow);\nfor(const origin of ['document'")
edit('graph_view.html', "manual:'Professor manual edit'", "manual:'Professor manual edit',student:'Validated student contribution'")
edit('graph_view.html', '>Manual edits</span>', '>Manual edits</span><span style="--color:#f472b6">Student contributions</span>')
edit('graph_view.html', 'purple means a professor manual edit.', 'purple means a professor manual edit; pink means a validated student contribution.')
edit('pipeline.professor_scope.py', 'Blue: document · orange: background', 'Blue: document · orange: background · purple: manual · pink: student contribution')
edit('professor.html', '<details class="card" id="learning-details">', '''<section class="card" id="contributions-panel"><h2>Student contributions</h2>
<p class="section-help">Extra claims are reviewed separately from quiz grades. Accepted additions appear in pink in Explore. Model reviews are not external verification. Uncertain claims wait here for professor review; quiz use requires separate approval in Run Insights.</p>
<div id="contribution-list"></div></section>
<details class="card" id="learning-details">''')
edit('professor.js', "if(S.tab==='insights')await runResults();}", "if(S.tab==='insights')await runResults();await loadContributions();}")
edit('professor.js', "return renderGraph().then(()=>tab==='insights'?runResults():null);", "return renderGraph().then(()=>tab==='insights'?runResults():null).then(loadContributions);")
edit('professor.js', "'Assessment saved.');\n}", """'Assessment saved.');
 if(result.contribution_answer_id){
  status('Grade saved. Checking extra claims separately...');
  try{const data=await api('answers/'+result.contribution_answer_id+'/contributions/check',{});
   await loadScope();const job=data.jobs.find(j=>j.answer_id===result.contribution_answer_id);
   status(job?.status==='completed'?'Grade saved. Contribution review completed.':'Grade saved. Contribution review needs attention in Student contributions.');
  }catch(error){status('Grade saved. Contribution check can be retried in Student contributions: '+error.message,true);}
 }
}
""")

path=root/'professor.js'
with path.open('a',encoding='utf-8') as f:
    f.write('''
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
''')
with (root/'professor.css').open('a',encoding='utf-8') as f:
    f.write('\n.contribution-card{border-left:4px solid #f472b6}.contribution-review{display:grid;gap:10px;margin-top:12px}.contribution-card pre{white-space:pre-wrap;overflow-wrap:anywhere}\n')
