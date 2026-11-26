"""Export the appended exercise without replacing any earlier profile reports."""
import json
import sys
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from pipeline.student_store import StudentStore
from pipeline.contributions import Contributions

WORK=ROOT/'outputs/student_profiles/additional_quizzes'


def main():
    ledger=json.loads((WORK/'metadata.json').read_text(encoding='utf-8'))
    store=StudentStore(ROOT/'outputs/professor/students.sqlite3')
    contributions=Contributions(store)
    notes=json.loads((WORK/'observations.json').read_text(encoding='utf-8')) if (WORK/'observations.json').exists() else {}
    summary=[]
    for profile in ledger['profiles']:
        name=profile['name'];student=ledger['students'][profile['key']]
        lines=[f'# {name}: additional quizzes','',
               '**Origin:** fictional learner with authored simulated responses, not a real student.','',
               f"**Profile:** {profile['profile']}. {profile['strengths']}",'',
               f"Student ID: `{student['id']}`.",'',
               'This append-only exercise plans two additional normal quizzes per topic, three questions per quiz. '
               'The limit applies only to the exercise process. Production interface, metrics, selection and grading remain unchanged. '
               'Answers were authored from the displayed question and targeted graph relationship, including its direction and conditions; '
               'no internet or hidden expected answers/criteria were used. Grades were not inserted, changed or pursued through revised submissions. '
               'The same request ID and text permit at most two attempts for technical failures.','',
               'Focus choices were planned before grading to sample different concepts through the existing focus control. '
               'Green relationships remain excluded, and normal adaptive selection can move beyond the requested focus. '
               'The intended profile is not a promised metric outcome.','']
        if profile['key']!='liam':
            lines += [f"[Earlier profile and preserved records](../{name.replace(' ','_')}.md).",'']
        else:
            lines += ['Specialty: the connected microglia branch within neurons and glia. Target graph edges: '+', '.join(ledger['specialty']['relationship_ids'])+'. '
                      'Other glial cells, neuron anatomy, AI and LLM tuning are outside this narrow specialty.','']
        overall=ledger.get('final_overall_metrics',{}).get(profile['key'])
        if overall:
            values=overall['graph_metrics']['values']
            lines += ['## Final All Topics view','',
                      f"Independent relationship coverage: **{values['relationship_coverage']}%**. Assessed coverage: **{values['assessment_coverage']}%**. "
                      f"Knowledge concentration (HHI): **{values['concentration'] if values['concentration'] is not None else 'unavailable'}**. "
                      f"These are the existing application metrics at {overall['at']}; no values were inserted. "
                      'Unavailable concentration means there is no independently mastered subgraph to measure.','']
        entries=[(k,e) for k,e in ledger['sessions'].items() if e['profile']==profile['key']]
        for round_number in (1,2):
            lines += [f'## Additional round {round_number}','',
                      '| Topic | Independent coverage before → after | Assessed coverage before → after | Average answer score before → after |',
                      '|---|---:|---:|---:|']
            for key,entry in entries:
                if entry['round']!=round_number: continue
                before=entry['before']['metrics'];after=entry.get('after',entry['before'])['metrics']
                values=[f"{before.get(field)} → {after.get(field)}" for field in ('knowledge_coverage','assessment_coverage','average_score')]
                lines += ['| '+entry['topic'].title()+' | '+' | '.join(values)+' |']
            lines += ['', 'Coverage percentages count graph relationships; answer averages also include previous sessions. '
                      'Incorrect, partial, assisted and pending responses do not establish independent mastery. '
                      'Revisiting an assessed fact can leave assessment coverage unchanged. '
                      'Accepted additions can enlarge the denominator without changing earlier mastery.','']
            for key,entry in entries:
                if entry['round']!=round_number: continue
                before=entry['before'];after=entry.get('after',before)
                lines += [f"### {entry['topic'].title()}",'',f"Session: `{entry.get('state',{}).get('id','not created')}`. Planned focus sequence: {', '.join(entry['focus_labels'])}.",'',
                          f"Independent relationships: {before['metrics']['independent']} → {after['metrics']['independent']}; assessed: {before['metrics']['assessed']} → {after['metrics']['assessed']}. "
                          f"Reference relationships: {before['unique_relationships']} → {after['unique_relationships']}.",'',
                          '| Existing graph metric | Before | After |','|---|---:|---:|']
                for metric,value in (before.get('graph_metrics') or {}).get('values',{}).items():
                    new=(after.get('graph_metrics') or {}).get('values',{}).get(metric)
                    lines += [f"| {metric.replace('_',' ')} | {value} | {new} |"]
                lines += ['', 'Null means unavailable, not a zero grade. Concentration and connectivity describe the measured subgraph, '
                          'so a few connected correct answers can have high concentration despite low overall coverage.','']
                gain=after['metrics']['independent']-before['metrics']['independent']
                assessed=after['metrics']['assessed']-before['metrics']['assessed']
                lines += [f"This round added {gain} independently demonstrated relationship(s) and {assessed} newly assessed relationship(s). "
                          +('No additional independent mastery was recorded; partial, assisted, incorrect and absent explanations cannot establish independent mastery. ' if not gain else 'The increase comes from the saved independent answer outcomes. ')
                          +('Assessment coverage can stay unchanged when a fact is revisited or no eligible question remains.' if not assessed else 'Newly assessed does not necessarily mean mastered.'),'']
                for number,submission in sorted(entry.get('submissions',{}).items(),key=lambda x:int(x[0])):
                    q=submission['question']
                    lines += [f'#### Question {number}','',q['text'],'','**Submitted answer:**','',
                              '> '+submission['answer'].replace('\n','\n> '),'',
                              f"Assistance: {q['hints']} hint(s); reveal: {q['revealed']}. Recorded score: {submission['score']}%.",'',
                              '**Recorded feedback:** '+submission['feedback'],'',
                              'Targeted graph reference: '+json.dumps(submission['reference_relationships'],ensure_ascii=False), '']
                    if q.get('help_text'): lines += ['Help shown: '+q['help_text'],'']
                    rows=contributions.rows(answer_id=submission['answer_id'])
                    lines += ['**Contributions and reviews:**','']
                    if not rows:
                        check=ledger['contributions'].get(submission['answer_id'],{})
                        lines += ['No candidate rows. Check status: '+check.get('job',{}).get('status','not requested')+'.','']
                    check=ledger['contributions'].get(submission['answer_id'],{})
                    if check.get('job',{}).get('error'):
                        lines += ['Contribution processing issue retained: '+check['job']['error'],'']
                    for row in rows:
                        lines += [f"- {row['claim']['statement']} — **{row['status']}**."]
                        for review in row.get('reviews',[]): lines += ['  '+review.get('reason',json.dumps(review,ensure_ascii=False))]
                        if row.get('validation_error'): lines += ['  Technical issue: '+str(row['validation_error'])]
                    lines += ['',f"Answer ID: `{submission['answer_id']}`. Saved: {submission['at']}.",'']
                if entry.get('stop_reason'):
                    lines += ['**Stopped early:** '+json.dumps(entry['stop_reason'],ensure_ascii=False),'']
                    for pending in store.pending_answers(entry['state']['id']) if entry.get('state') else []:
                        lines += ['Pending question: '+entry['state']['state']['question']['text'],'',
                                  'Original ungraded submission: '+pending['text'],'']
        if notes.get(profile['key']): lines += ['## Observations retained','']+['- '+n for n in notes[profile['key']]]+['']
        lines += ['## Audit trail','',f"Pre-exercise database backup: `{ledger['backup']}`. Full immutable request bodies, bounded retry history, graph references and metric snapshots are in `metadata.json`. Authored answers are in `answers_r*.json`.",'',
                  'Previous records, pending answers and contribution decisions were preserved. No administrative correction was mixed into natural student performance. '
                  'Local model grading and contribution decisions can be surprising or wrong; their actual results remain recorded. '
                  'This small, deliberately focused exercise does not establish full-topic mastery.','']
        target=WORK/(name.replace(' ','_')+'.md');target.write_text('\n'.join(lines),encoding='utf-8')
        summary.append(dict(name=name,planned_sessions=len(entries),sessions=sum(bool(e.get('state')) for _,e in entries),graded_answers=sum(len(e.get('submissions',{})) for _,e in entries),document=target.name))
    (WORK/'summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    readme=['# Additional student quizzes','',
            'This is an append-only fictional population exercise. Existing students, answers, sessions, pending grades and reviews are preserved. '
            'Liam Morgan was added as a concept specialist in microglia, within Elena Morales\'s neurons-and-glia topic. '
            'Names in the normal interface have no profile or simulation labels; the fictional origin is documented here and in metadata.','',
            'The plan is six new normal quizzes per student, two per topic, with three questions per quiz. '
            'The production default and selection/grading rules are unchanged. Eligibility exhaustion and unresolved technical failures can shorten the plan.','',
            '| Student | New quizzes created | New graded answers | Record |','|---|---:|---:|---|']
    for row in summary:
        readme += [f"| {row['name']} | {row['sessions']} / {row['planned_sessions']} | {row['graded_answers']} | [Questions, answers, outcomes and metrics]({row['document']}) |"]
    outcome=ledger.get('outcome_summary',{})
    readme += ['', 'Maya had already mastered four of the five quiz-eligible AI Test facts. Her first new AI quiz assessed the remaining fact and ended; '
               'her second AI start reported that no eligible unmastered facts remained. Review mode was not enabled to fill the quota.','',
               f"All {outcome.get('graded_answers',0)} new submissions have grades; the three original pending grades remain unchanged. "
               f"Contribution checks: {outcome.get('contribution_jobs',{}).get('completed',0)} completed and {outcome.get('contribution_jobs',{}).get('needs_review',0)} require technical review. "
               'Their errors and actual candidate decisions are retained in the student reports and audit ledger.','',
               '## Final All Topics metrics','',
               '| Student | Independent relationship coverage | Knowledge concentration (HHI) |','|---|---:|---:|']
    for profile in ledger['profiles']:
        overall=ledger.get('final_overall_metrics',{}).get(profile['key'])
        if overall:
            values=overall['graph_metrics']['values']
            readme += [f"| {profile['name']} | {values['relationship_coverage']}% | {values['concentration'] if values['concentration'] is not None else 'Unavailable'} |"]
    readme += ['', 'Higher HHI indicates greater concentration in the existing reference-community calculation. It is not an overall ability score. '
               'Noah has no independent mastery, so HHI is unavailable. Liam\'s microglia facts form one connected mastered component, '
               'but cross a reference-community boundary; a connected specialty need not yield HHI = 1.','']
    readme += ['', '## Current independent relationship coverage','',
               '| Student | AI Test | LLM tuning | Neurons and glia |','|---|---:|---:|---:|']
    for profile in ledger['profiles']:
        cells=[]
        for topic in ('ai test','llm tuning','neurons and glia'):
            candidates=[e for e in ledger['sessions'].values() if e['profile']==profile['key'] and e['topic']==topic]
            final=max(candidates,key=lambda e:e['round'])
            metrics=final.get('after',final['before'])['metrics']
            cells.append(f"{metrics['knowledge_coverage']}% ({metrics['independent']} relationships)")
        readme += ['| '+profile['name']+' | '+' | '.join(cells)+' |']
    readme += ['', 'Graph coverage includes relationships that are not yet quiz-approved. Therefore mastering every currently eligible '
               'document relationship does not necessarily produce 100% graph coverage. Detailed degree, connectivity and concentration metrics '
               'are the existing application values, recorded before and after each round in each student document. No values were inserted or tuned.','',
               '## Procedure and limitations','',
               '- Questions were generated and answers submitted through the actual local-model quiz API. Authored answer files were fixed before submission.',
               '- Answers used the targeted relationship, its direction, conditions and qualifiers, together with the fictional profile. No internet research or hidden expected answers/criteria were used.',
               '- Concept focus choices were planned before results; adaptive selection and green-fact exclusion remained in control.',
               '- Repeated questions across sessions can arise from normal progress selection. No completed answer was resubmitted to obtain a different outcome.',
               '- Technical grading failures permit at most two HTTP attempts with the same request ID and unchanged answer. Contribution validation failures and review decisions are preserved.',
               '- Normal contribution checks were requested separately from grading. No professor approvals, corrections or grade overrides were added.',
               '- These short, deliberately focused samples illustrate measured coverage; they do not prove complete topic knowledge.','',
               f"Backup: `{ledger['backup']}`. Verification: [verification.json](verification.json). Full request/response audit and metric snapshots: [metadata.json](metadata.json). Earlier exercise: [original reports](../README.md).",'']
    (WORK/'README.md').write_text('\n'.join(readme),encoding='utf-8')
    print(json.dumps(summary,indent=2))


if __name__=='__main__': main()
