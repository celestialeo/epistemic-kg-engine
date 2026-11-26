"""Render readable fictional-student records from actual saved API outcomes."""
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from pipeline.student_store import StudentStore
from pipeline.contributions import Contributions

WORK=ROOT/'outputs/student_profiles'


def pct(value):
    return 'Unassessed' if value is None else f'{value:g}%'


def relationship_notes(checkpoint, question):
    graph=checkpoint['graph_snapshot']
    names={n['id']:n['label'] for n in graph['nodes']}
    ids={f['id'] for f in question['examiner_material']['facts']}
    notes=[]
    for fact in graph['edges']:
        if fact['id'] not in ids: continue
        line=f"{names[fact['source']]} → {fact['label'].replace('_',' ')} → {names[fact['target']]}"
        details=[fact.get(k) for k in ('conditions','modality','purpose','timing') if fact.get(k)]
        details += fact.get('argument_qualifiers') or []
        if details: line += ' ('+'; '.join(details)+')'
        notes.append(line)
    return notes


def main():
    ledger=json.loads((WORK/'metadata.json').read_text(encoding='utf-8'))
    observations=json.loads((WORK/'observations.json').read_text(encoding='utf-8')) if (WORK/'observations.json').exists() else {}
    store=StudentStore(ROOT/'outputs/professor/students.sqlite3')
    answers={a['id']:a for a in store.answers()}
    contributions=Contributions(store)
    for profile in ledger['profiles']:
        student=ledger['students'][profile['key']]
        lines=[f"# {profile['name']}", '',
               '**Origin:** fictional student, authored for this project exercise; these are not observations of a real learner.', '',
               f"**Profile:** {profile['profile']}. {profile['strengths']}", '',
               'Questions, grades, assistance and contribution decisions below come from the normal saved quiz workflow. '
               'Initial-round answers were authored from displayed questions and explicitly requested help. For the follow-up round, '
               'the user requested answers grounded in the targeted graph relationship: meaning, direction and conditions. '
               'No internet research or hidden expected answers/grading criteria were used to author responses. '
               'Unexpected grades were retained. The profile describes intended prior knowledge, not a guaranteed measured result.', '',
               'Two questions per topic per round bound this exercise. Production round sizing, deterministic progress selection, '
               'grading weights and mastery rules were not changed. These small samples cannot establish topic-wide mastery.', '',
               f"Student ID: `{student['id']}`. Backup before replacement: `{ledger['backup']}`.", '']
        for round_number in (1,2):
            lines += [f'## Round {round_number}', '',
                      '| Topic | Independent coverage before → after | Assessed coverage before → after | Answer score before → after |',
                      '|---|---:|---:|---:|']
            sessions=[(key,e) for key,e in ledger['sessions'].items() if e['profile']==profile['key'] and e['round']==round_number]
            for key,entry in sessions:
                before=entry['before']['metrics'];after=entry.get('after',entry['before'])['metrics']
                values=[f"{pct(before.get(k))} → {pct(after.get(k))}" for k in ('knowledge_coverage','assessment_coverage','average_score')]
                lines.append('| '+entry['topic'].title()+' | '+' | '.join(values)+' |')
            lines += ['', 'Coverage counts the saved graph, including any accepted additions. A correct independent full relationship can '
                      'increase independent coverage. Assisted or partial evidence remains eligible; incorrect or absent explanations do not '
                      'add mastery. Reassessing the same relationship may change a score without increasing assessed coverage. '
                      'Adding a new unassessed contribution can enlarge the denominator and reduce coverage without losing learned facts.', '']
            for key,entry in sessions:
                lines += [f"### {entry['topic'].title()}", '', f"Session: `{entry.get('state',{}).get('id','not created')}`.", '']
                before=entry['before'];after=entry.get('after',before)
                lines += [f"Reference relationships: {before['unique_relationships']} → {after['unique_relationships']}.", '',
                          f"Before categories: `{json.dumps(before['categories'],sort_keys=True)}`.",
                          f"After categories: `{json.dumps(after['categories'],sort_keys=True)}`.", '']
                b=before['metrics'];a=after['metrics']
                lines += [f"Independent relationships: {b['independent']} → {a['independent']}; "
                          f"assessed relationships: {b['assessed']} → {a['assessed']}. "
                          'These are counts of demonstrated relationships, not points inserted for the profile.', '']
                gain=a['independent']-b['independent']
                lines += [(f'{gain} additional relationship(s) now have independent evidence.' if gain>0 else
                           'No additional independent relationship was established in this round. Partial, assisted, incorrect and pending answers cannot add independent mastery.'), '']
                if a['assessed']==b['assessed']:
                    lines += ['The number of assessed relationships did not change: revisiting an already assessed fact or retaining an unresolved submission adds no newly assessed relationship.', '']
                gb=before.get('graph_metrics',{}).get('values',{})
                ga=after.get('graph_metrics',{}).get('values',{})
                if gb and ga:
                    lines += ['<details><summary>Graph metrics before and after this round</summary>', '',
                              '| Metric | Before | After |', '|---|---:|---:|']
                    for metric in gb:
                        lines.append(f"| {metric.replace('_',' ').title()} | {gb[metric] if gb[metric] is not None else 'Unavailable'} | {ga.get(metric) if ga.get(metric) is not None else 'Unavailable'} |")
                    lines += ['', 'Coverage, concept reach/completeness, largest component and density are percentages; '
                              'other entries are counts or dimensionless graph statistics. A sparse sample can leave clustering '
                              'at zero or cross-topic coverage unavailable. Unavailable is not a zero grade.', '', '</details>', '']
                for number, submission in sorted(entry.get('submissions',{}).items(),key=lambda kv:int(kv[0])):
                    answer=answers[submission['answer_id']]
                    q=submission['question']
                    lines += [f"#### Question {number}", '', q['text'], '', '**Submitted answer:**', '', '> '+submission['answer'].replace('\n','\n> '), '',
                              f"**Assistance:** {q['hints']} hint(s); reveal {'used' if q['revealed'] else 'not used'}. "
                              f"**Recorded score:** {pct(answer['score'])}. **Saved:** {answer['created_at']}.", '']
                    # Help history is learner-visible, unlike examiner material.
                    checkpoint=store.session(answer['session_id'])['checkpoint']
                    if round_number==2:
                        lines += ['Targeted graph reference used for authoring: '+'; '.join(relationship_notes(checkpoint,answer['question']))+'.', '']
                    for event in checkpoint.get('history',[]):
                        if event.get('action') in ('hint','reveal') and event.get('question_id')==q['id']:
                            lines += [f"Assistance record: `{json.dumps(event,ensure_ascii=False)}`", '']
                    if q.get('help_text'):
                        lines += ['Help shown: '+q['help_text'], '']
                    lines += ['**Recorded outcome:** '+answer['effective_feedback'], '']
                    if answer['overrides']:
                        lines += ['Professor corrections: '+json.dumps(answer['overrides'],ensure_ascii=False), '']
                    rows=contributions.rows(answer_id=answer['id'])
                    job=next((j for j in contributions.jobs(entry['run_id']) if j['answer_id']==answer['id']),None)
                    lines += ['**Contributions and review:**', '']
                    if not rows:
                        lines += ['No candidate contributions recorded. Check status: '+(job['status'] if job else 'not requested')+'.', '']
                    for row in rows:
                        lines += [f"- {row['claim']['statement']} — **{row['status']}**."]
                        for review in row.get('reviews',[]):
                            lines += ['  '+review.get('reason',json.dumps(review,ensure_ascii=False))]
                        for review in row.get('professor_reviews',[]):
                            lines += ['  Professor decision: '+json.dumps(review,ensure_ascii=False)]
                        if row.get('validation_error'): lines += ['  Technical review issue: '+str(row['validation_error'])]
                    if job and job.get('error'): lines += ['Contribution processing issue: '+job['error']]
                    lines += ['',f"Answer ID: `{answer['id']}`.", '']
                pending=store.pending_answers(entry['state']['id']) if entry.get('state') else []
                for item in pending:
                    q=entry['state']['state']['question']
                    lines += [f"#### Pending question {q['number']}", '', q['text'], '',
                              '**Unresolved submitted answer (no grade assigned):** '+item['text'], '',
                              f"Assistance: {q['hints']} hint(s); reveal {'used' if q['revealed'] else 'not used'}. Saved: {item['created_at']}.", '',
                              'Help shown: '+(q.get('help_text') or 'None.'), '', item.get('error',''), '']
                    if round_number==2:
                        checkpoint=store.session(entry['state']['id'])['checkpoint']
                        lines += ['Targeted graph reference used for authoring: '+'; '.join(relationship_notes(checkpoint,checkpoint['question']))+'.', '']
                retries=[(k,v) for k,v in ledger['commands'].items() if k.startswith(key+':') and any(a['status']!=200 for a in v['attempts'])]
                if retries:
                    lines += ['**Technical failures retained:**', '']
                    for command_key,record in retries:
                        lines += [f"- `{command_key}`: {len(record['attempts'])} HTTP attempt(s); final status {record['status']}. Original answer and request ID preserved."]
                        if record.get('diagnostic_fix_retry'): lines += ['  '+record['diagnostic_fix_retry']]
                    lines += ['']
        notes=observations.get(profile['key'],[])
        if notes:
            lines += ['## Observed issues retained', '']+[f'- {note}' for note in notes]+['']
        lines += ['## Interpretation and limits', '',
                  'Grades reflect this local model and the saved reference graph. A zero can result from narrow interpretation of a broadly '
                  'worded question; an admitted uncertainty can be graded as partial even when part of the explanation is correct. '
                  'Read the exact questions, answers and feedback above rather than inferring ability from the intended profile.', '',
                  'Contribution checks use model knowledge, not external source verification. Accepted contributions do not directly award '
                  'mastery and require separate professor approval before becoming quiz material. No natural student answer was changed '
                  'or repeated to obtain a desired result. Administrative correction, approval/rejection/undo, failure and restart checks '
                  'used isolated fixture records, outside these student histories.', '',
                  'Machine-readable provenance, requests and metric snapshots: `metadata.json`. Authored responses: `answers_r*.json`.', '']
        (WORK/(profile['name'].replace(' ','_')+'.md')).write_text('\n'.join(lines),encoding='utf-8')
        print(profile['name'])


if __name__=='__main__':
    main()
