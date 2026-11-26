from .settings import setting
"""Read-only topic scopes and conservative cross-topic learning summaries."""
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path

from .knowledge import metrics, display_state, mean, percentage, retain_mastery, scope_graph_metrics


def stamp(run):
    manifest = run['snapshot']['manifest']
    value = manifest.get('started_at_utc') or manifest.get('started_at')
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
    except (ValueError, AttributeError):
        return 0


def describe(run):
    manifest = run['snapshot']['manifest']
    return dict(id=run['id'], topic_key=run['topic_key'], title=run['title'],
                run_name=Path(run['directory']).name, started_at=manifest.get('started_at_utc') or manifest.get('started_at'),
                status=manifest.get('status'), concepts=run['snapshot']['graph']['nodes'],
                relationships=len(run['snapshot']['graph']['edges']))


def select_runs(runs, topic=None, run_id=None):
    """All Topics includes exactly one latest version per input topic."""
    latest = {}
    for run in runs:
        if run['topic_key'] not in latest or (stamp(run), run['id']) > (stamp(latest[run['topic_key']]), latest[run['topic_key']]['id']):
            latest[run['topic_key']] = run
    if not topic:
        if run_id:
            raise ValueError('Select a topic before choosing a historical version')
        return sorted(latest.values(), key=lambda r: (r['title'], r['topic_key']))
    if topic not in latest:
        raise ValueError('Topic is unavailable; refresh the saved run list')
    if run_id:
        run = next((r for r in runs if r['id'] == run_id), None)
        if not run or run['topic_key'] != topic:
            raise ValueError('The selected run does not belong to this topic')
        return [run]
    return [latest[topic]]


def identifier(kind, value):
    return kind + '_' + hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()[:24]


def union_graph(runs):
    """Count identical recorded semantics once; retain every source reference.

    No synonym matching. Endpoints include label/definition/kind, directed edges
    retain all non-provenance fields, including conditions, modality and polarity.
    """
    nodes, edges, mapping = {}, {}, {}
    provenance = {'id', 'source', 'target', 'evidence', 'supporting_evidence', 'origin',
                  'chunk_id', 'paragraph_id', 'evidence_start', 'evidence_end',
                  'confidence', 'score', 'scores', 'candidate_id', 'seed_id', 'source_order'}
    from .graph_edits import semantics
    for run in runs:
        graph = run['snapshot']['graph']
        meanings = semantics(graph)
        node_ids = {}
        for node in graph['nodes']:
            key = identifier('concept', {k: node.get(k) for k in ('label', 'definition', 'kind')})
            node_ids[node['id']] = key
            nodes.setdefault(key, {**node, 'id': key, 'sources': []})
            nodes[key]['sources'].append(dict(run_id=run['id'], run_name=Path(run['directory']).name, topic=run['title']))
        for edge in graph['edges']:
            semantic = {k: v for k, v in edge.items() if k not in provenance}
            if edge.get('participants'):
                semantic['participants'] = [dict(p, node=node_ids[p['node']]) for p in edge['participants']]
            key = identifier('fact', meanings[edge['id']])
            mapping[(run['id'], edge['id'])] = key
            edges.setdefault(key, {**edge, **semantic, 'id': key, 'source': node_ids[edge['source']],
                                   'target': node_ids[edge['target']], 'sources': []})
            edges[key]['sources'].append(dict(run_id=run['id'], run_name=Path(run['directory']).name,
                topic=run['title'], fact_id=edge['id'], origin=edge.get('origin'), evidence=edge.get('evidence'),
                supporting_evidence=edge.get('supporting_evidence', [])))
            if edge.get('origin') == 'document':
                edges[key]['origin'] = 'document'
    return dict(run_id='All Topics — latest source version per topic', nodes=list(nodes.values()), edges=list(edges.values())), mapping


def evidence_order(fact):
    return (fact.get('at') or '', fact.get('answer_id') or '', fact.get('source_run_id') or '')


def categories(graph, facts):
    counts = Counter()
    for edge in graph['edges']:
        fact = facts.get(edge['id'])
        state = ('unassessed' if not fact else 'independent' if fact['mark'] == 'match' and not fact['helped']
                 else 'assisted_correct' if fact['mark'] == 'match' else 'partial' if fact['mark'] == 'related'
                 else 'incorrect' if fact['mark'] == 'conflict' else 'not_demonstrated')
        counts[state] += 1
    return {key: counts[key] for key in ('independent', 'assisted_correct', 'partial', 'incorrect', 'not_demonstrated', 'unassessed')}


DEFINITIONS = {
    'Scope': 'A specific topic uses the selected saved graph version. All Topics uses the latest registered version of each input topic, including retained snapshots whose source folders are no longer available.',
    'Unique relationships': 'All Topics counts an exact recorded semantic relationship once across topics. Endpoint names, definitions, kinds, direction, relation fields, conditions and modality must agree. Quotes, generated IDs and provenance do not make a second relationship. No synonyms or paraphrases are inferred.',
    'Knowledge coverage': 'Independently correct unique relationships / all unique relationships in this scope. An independently correct demonstration remains earned across later quizzes. Later partial, incorrect or assisted answers keep their own scores without erasing green. Effective professor corrections can revoke invalid credit. Exact transfers retain their source; no evidence means unassessed.',
    'Assessment coverage': 'Unique relationships with any assessed answer / all unique relationships. Incorrect, partial, assisted and independently correct remain distinct.',
    'Answer performance': 'Average score of the latest answer to each distinct session/question on the included source versions. Assisted and independent scores are separate. Revisions do not inflate the denominator. This measures question attempts, not unique fact coverage; different questions may test the same fact.',
    'Class averages': 'Each roster member has equal weight. Coverage includes unassessed students; unavailable answer scores are excluded, with n shown. Relationship proportions use the full roster and also show assessed counts.',
    'Topic breakdowns': 'Each topic uses its own source graph and evidence. Topic rows can overlap and must not be added or averaged to obtain All Topics coverage. Provisional judgments can differ between topics; earned independent mastery transfers only across exact, unambiguous semantic matches.',
    'Quizzes': 'Every quiz belongs to one student and one source run. In All Topics, suggested runs prioritize remaining unique gaps; a quiz can use exactly matching evidence from the included topics to avoid re-testing known facts. This does not copy grades or change stored histories.',
    'History': 'The history list includes every version of the selected input topic, or all topics, and labels whether each session contributes to current-version metrics. Resuming a historical quiz explicitly selects its original topic and run.',
    'Corrections and versions': 'Overrides keep their audit history. Mastery is recomputed from all effective answers: green remains while any valid independent demonstration supports the fact. Correct every erroneous supporting award to revoke green. Cross-version and cross-topic transfers retain source run, fact, answer and date; answer scores are never copied.',
    'Connectivity': 'Connected understanding is the largest undirected independently mastered component / all mastered endpoint concepts. Fragmentation counts mastered components; a singleton can only come from a self-relationship. No mastered concepts means unavailable connectivity.',
    'Concentration': 'Sum of squared shares of independently mastered facts across deterministic graph communities (HHI). Near 1 means concentrated knowledge. Graph communities are not input topics. No mastered facts means unavailable.',
    'Progress': 'Per-source progress recalculates coverage and latest-per-question performance after each answer, with corrections reflected retrospectively. Transferred evidence is a labelled starting baseline. Separate source versions are never joined into a fabricated trend.',
}


def summarize_scope(store, topic=None, run_id=None, student_id=None, source_run_ids=None):
    runs = store.runs()
    by_id = {r['id']: r for r in runs}
    # Persisted quiz contexts pin their original source set, even after newer runs.
    # This internal option is not exposed by the shared-scope HTTP endpoint.
    selected_runs = ([by_id[key] for key in dict.fromkeys(source_run_ids)]
                     if source_run_ids is not None else select_runs(runs, topic, run_id))
    included = {r['id'] for r in selected_runs}
    history = store.history()
    graph, mapping = union_graph(selected_runs)
    if topic and selected_runs:
        graph['run_id'] = Path(selected_runs[0]['directory']).name
    rows, topic_rows, projection = [], [], {}
    for student in store.students():
        facts, per_run = {}, {}
        for run in selected_runs:
            current = store._knowledge(student['id'], run['id'], by_id, history)
            per_run[run['id']] = current
            for edge_id, fact in current.items():
                key = mapping.get((run['id'], edge_id))
                if key:
                    prior = facts.get(key)
                    if prior is None or evidence_order(fact) >= evidence_order(prior):
                        facts[key] = retain_mastery(prior, fact)
                    else:
                        facts[key] = retain_mastery(fact, prior)
        attempts = []
        for session in history:
            if session['student_id'] == student['id'] and session['run_id'] in included:
                for answer in session['answers']:
                    attempts.append({**answer, 'question': {**answer['question'], 'id': session['id'] + ':' + answer['question']['id']}})
        attempts.sort(key=lambda a: (a['created_at'], a['id']))
        m = metrics(graph, facts, attempts)
        rows.append(dict(**student, metrics=m, categories=categories(graph, facts),
                         state=display_state(graph, facts), knowledge=facts))
        if student['id'] == student_id:
            projection = {run['id']: {e['id']: facts[mapping[(run['id'], e['id'])]]
                          for e in run['snapshot']['graph']['edges'] if mapping[(run['id'], e['id'])] in facts}
                          for run in selected_runs}
        for run in selected_runs:
            attempts_for_run = [a for s in history if s['student_id'] == student['id'] and s['run_id'] == run['id'] for a in s['answers']]
            topic_rows.append(dict(student_id=student['id'], run_id=run['id'],
                metrics=metrics(run['snapshot']['graph'], per_run[run['id']], attempts_for_run),
                categories=categories(run['snapshot']['graph'], per_run[run['id']])))
    fields = ('knowledge_coverage', 'assessment_coverage', 'average_score', 'independent_score', 'assisted_score',
              'connected_understanding', 'mastered_components', 'isolated_mastered_concepts', 'concentration')
    averages = {key: dict(value=mean([row['metrics'][key] for row in rows]),
                          n=sum(row['metrics'][key] is not None for row in rows)) for key in fields}
    selected = next((row for row in rows if row['id'] == student_id), None)
    breakdown, class_breakdown = [], []
    for run in selected_runs:
        entries = [row for row in topic_rows if row['run_id'] == run['id'] and (not student_id or row['student_id'] == student_id)]
        descriptor = describe(run)
        descriptor.update(knowledge_coverage=mean([row['metrics']['knowledge_coverage'] for row in entries]),
            assessment_coverage=mean([row['metrics']['assessment_coverage'] for row in entries]),
            average_score=mean([row['metrics']['average_score'] for row in entries]),
            assessed_students=sum(row['metrics']['assessed'] > 0 for row in entries), students=len(entries),
            counts={key: sum(row['categories'][key] for row in entries) for key in categories(run['snapshot']['graph'], {})})
        breakdown.append(descriptor)
        cohort = [row for row in topic_rows if row['run_id'] == run['id']]
        class_breakdown.append(dict(**describe(run),
            knowledge_coverage=mean([row['metrics']['knowledge_coverage'] for row in cohort]),
            assessment_coverage=mean([row['metrics']['assessment_coverage'] for row in cohort]),
            average_score=mean([row['metrics']['average_score'] for row in cohort]),
            assessed_students=sum(row['metrics']['assessed'] > 0 for row in cohort), students=len(cohort)))
    overlay = []
    for edge in graph['edges']:
        evidence = [row['knowledge'][edge['id']] for row in rows if edge['id'] in row['knowledge']]
        known = sum(f['mark'] == 'match' and not f['helped'] for f in evidence)
        difficulty = sum(f['mark'] != 'match' for f in evidence)
        helped = sum(f['mark'] == 'match' and f['helped'] for f in evidence)
        overlay.append(dict(id=edge['id'], source=edge['source'], target=edge['target'], label=edge['label'],
            known=known, assessed=len(evidence), students=len(rows), difficulty=difficulty, assisted=helped,
            proportion=known/len(rows) if rows else None, sources=edge['sources']))
    scoped_history = []
    for session in reversed(history):
        if student_id and session['student_id'] != student_id:
            continue
        if topic and by_id[session['run_id']]['topic_key'] != topic:
            continue
        scoped_history.append({**{k: v for k, v in session.items() if k != 'answers'},
            'topic_key': by_id[session['run_id']]['topic_key'], 'included_in_metrics': session['run_id'] in included,
            'pending': bool(store.pending_answers(session['id']))})
    recommendations = []
    if selected:
        for run in selected_runs:
            ids = {mapping[(run['id'], e['id'])] for e in run['snapshot']['graph']['edges']}
            remaining = [key for key in ids if key not in selected['knowledge'] or
                         selected['knowledge'][key]['mark'] != 'match' or selected['knowledge'][key]['helped']]
            if remaining:
                recommendations.append(dict(run_id=run['id'], title=run['title'], remaining=len(remaining), total=len(ids)))
        recommendations.sort(key=lambda row: (-row['remaining'], row['title'], row['run_id']))
    analytics = scope_graph_metrics(graph, rows)
    return dict(analytics=analytics, topic=topic, all_topics=not bool(topic), runs=[describe(r) for r in selected_runs],
        unique_relationships=len(graph['edges']), source_relationships=sum(len(r['snapshot']['graph']['edges']) for r in selected_runs),
        graph=graph, students=rows, selected=selected, averages=averages, topics=breakdown, class_topics=class_breakdown,
        history=scoped_history, overlay=overlay, projected_knowledge=projection,
        recommendations=recommendations,
        strengths=sorted([r for r in overlay if r['known']], key=lambda r: (-r['known'], r['id']))[:setting('ui', 'professor_summary_items')],
        difficulties=sorted([r for r in overlay if r['difficulty'] or r['assisted']], key=lambda r: (-(r['difficulty']+r['assisted']), r['id']))[:setting('ui', 'professor_summary_items')],
        definitions=DEFINITIONS)


def scope_graph_page(summary, mode='class'):
    """Use the existing interactive graph for a read-only aggregate, with provenance."""
    from .graph_view import render_graph
    state = summary['selected']['state'] if mode == 'student' and summary['selected'] else None
    overlay = summary['overlay'] if mode == 'class' else []
    graph = {**summary['graph'], 'scope_state': state, 'scope_overlay': overlay}
    page = render_graph(graph)
    script = '''<style>header{padding:14px 20px}header h1{font-size:22px}.graph-shell{margin:10px}main{height:550px}body{background:#101827}</style><script>
    const savedHighlight=highlight;
    const scopeColors={match:'#54d99a',related:'#f3bf62',conflict:'#ff7e8b',not_demonstrated:'#ff7e8b'};
    highlight=function(){savedHighlight();if(data.scope_state)for(const node of visible){node.element.querySelector('circle').setAttribute('fill',scopeColors[data.scope_state.node_status[node.id]]||'#62738d');}for(const edge of links){let color=null,width=2;const row=data.scope_overlay.find(r=>r.id===edge.id);
      if(data.scope_state)color=scopeColors[data.scope_state.edge_status[edge.id]]||'#62738d';
      else if(row){color=row.proportion===null?'#62738d':`hsl(150 55% ${28+row.proportion*40}%)`;width=2+5*(row.proportion||0);}
      if(color){edge.line.setAttribute('stroke',color);edge.line.setAttribute('stroke-width',width);const markerId='scope-arrow-'+edge.id;let marker=document.getElementById(markerId);if(!marker){marker=el('marker',{id:markerId,viewBox:'0 0 10 10',refX:9,refY:5,markerWidth:6,markerHeight:6,orient:'auto-start-reverse'},svg.querySelector('defs'));el('path',{d:'M 0 0 L 10 5 L 0 10 z',fill:color},marker);}edge.line.setAttribute('marker-end','url(#'+markerId+')');}
      if(row)edge.group.querySelector('title').textContent=`${row.known}/${row.students} independently know; ${row.assessed}/${row.students} assessed`;
    }};
    document.querySelector('.legend').textContent=data.scope_state?'Green: independently correct · amber: partial / assisted · red: incorrect / not demonstrated · gray: unassessed':data.scope_overlay.length?'Brighter and thicker: more of the class independently know · gray: unavailable':'Blue: document · orange: background · purple: manual · pink: student contribution';
    if(data.scope_state){
      $('hint').textContent='Select a concept or relationship to inspect saved student evidence.';
      document.querySelector('main aside>p.muted').textContent='Green means independent mastery; amber means partial or assisted evidence; red means incorrect or not demonstrated; gray means unassessed. Pink outlines identify student additions. Unassessed is not incorrect.';
    }else if(data.scope_overlay.length){
      $('hint').textContent='Select a relationship to inspect its meaning; hover for class knowledge and assessment counts.';
      document.querySelector('main aside>p.muted').textContent='Brighter and thicker relationships are independently known by a larger share of the class. Gray means the roster proportion is unavailable. These are learning indicators, not source-graph quality scores.';
    }
    $('run').textContent=data.run_id+' · Open a source topic for statement comparison or a source-grounded quiz. Select an arrow to see every source run.';
    highlight();
    </script>'''
    return page.replace('</html>', script + '<link rel="stylesheet" href="/professor-graph.css"></html>')
