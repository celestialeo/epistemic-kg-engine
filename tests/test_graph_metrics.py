"""Analytical graph shapes and evidence boundaries for the twelve UI metrics."""
import unittest

from pipeline.knowledge import graph_metrics, scope_graph_metrics
from tests import test_professor as fixtures


def graph(nodes, pairs):
    return dict(nodes=[dict(id=n, label=n) for n in nodes],
                edges=[dict(id=str(i), source=a, target=b, label='links') for i, (a,b) in enumerate(pairs)])


def evidence(*ids, mark='match', helped=False):
    return {str(i): dict(mark=mark, helped=helped) for i in ids}


class GraphMetricMathTests(unittest.TestCase):
    def test_triangle_degree_density_clustering_and_efficiency(self):
        g=graph('abc', [('a','b'),('b','c'),('a','c')])
        m=graph_metrics(g,evidence(0,1,2),dict.fromkeys('abc','a'))
        self.assertEqual(m['values'], dict(relationship_coverage=100,assessment_coverage=100,
            concept_reach=100,concept_completeness=100,average_degree=2,density=100,
            components=1,largest_component=100,clustering=1,cross_topic_coverage=None,
            global_efficiency=1,modularity=0,concentration=1,connection_strength=2))

    def test_efficiency_uses_all_reference_nodes_and_disconnected_pairs(self):
        g=graph('abcd',[('a','b'),('b','c')])
        m=graph_metrics(g,evidence(0,1))
        self.assertEqual(m['values']['global_efficiency'],.417)  # (1+1+1/2)*2 / 12
        self.assertEqual(m['values']['density'],66.67)
        self.assertEqual(m['values']['concept_reach'],75)
        self.assertEqual(m['values']['average_degree'],1.333)
        self.assertEqual(m['values']['clustering'],0)

    def test_parallel_reverse_and_self_facts_do_not_inflate_topology(self):
        g=graph('ab',[('a','b'),('a','b'),('b','a'),('a','a')])
        m=graph_metrics(g,evidence(0,1,2,3))
        self.assertEqual(m['known'],4)
        self.assertEqual(m['links'],1)
        self.assertEqual(m['values']['density'],100)
        self.assertEqual(m['values']['connection_strength'],3.5)
        self.assertEqual([(c['degree'],c['in_degree'],c['out_degree']) for c in m['concepts']],[(1,1,1),(1,1,1)])

    def test_help_partial_incorrect_and_unknown_are_not_mastery(self):
        g=graph('abcde',[('a','b'),('b','c'),('c','d'),('d','e')])
        facts={**evidence(0,helped=True),**evidence(1,mark='related'),**evidence(2,mark='conflict')}
        m=graph_metrics(g,facts)
        self.assertEqual(m['values']['relationship_coverage'],0)
        self.assertEqual(m['values']['assessment_coverage'],75)
        self.assertIsNone(m['values']['global_efficiency'])
        self.assertIsNone(m['values']['components'])
        self.assertIsNone(m['values']['concentration'])
        self.assertEqual(m['reached'],0)

    def test_fixed_partition_modularity_bridges_and_concentration(self):
        g=graph('abcd',[('a','b'),('c','d'),('b','c')])
        partition=dict(a='a',b='a',c='c',d='c')
        m=graph_metrics(g,evidence(0,1),partition)
        self.assertEqual(m['values']['modularity'],.5)
        self.assertEqual(m['values']['cross_topic_coverage'],0)
        self.assertEqual(m['values']['concentration'],.5)
        self.assertEqual(m['values']['components'],2)
        self.assertEqual(m['values']['largest_component'],50)
        self.assertEqual(graph_metrics(g,evidence(0,1,2),partition)['values']['cross_topic_coverage'],100)

    def test_class_mean_is_not_combined_graph_and_zero_evidence_is_explicit(self):
        g=graph('abc',[('a','b'),('b','c')])
        rows=[dict(knowledge=evidence(0)),dict(knowledge=evidence(1)),dict(knowledge={})]
        m=scope_graph_metrics(g,rows)
        self.assertEqual(m['averages']['relationship_coverage']['value'],33.333)
        self.assertEqual(m['averages']['average_degree']['n'],2)
        self.assertEqual(m['averages']['average_degree']['value'],1)
        self.assertEqual(m['collective_coverage'],100)
        self.assertEqual(m['shared_coverage'],0)
        b=next(c for c in m['concepts'] if c['id']=='b')
        self.assertEqual(b['strength'],.667)
        self.assertEqual(b['completeness'],33.3)

    def test_reference_includes_isolates_and_empty_roster_is_unavailable(self):
        m=scope_graph_metrics(graph('abc',[('a','b')]),[])
        self.assertEqual(m['reference']['values']['average_degree'],.667)
        self.assertEqual(m['reference']['values']['density'],33.33)
        self.assertEqual(m['reference']['values']['components'],2)
        self.assertEqual(m['reference']['values']['largest_component'],66.7)
        self.assertIsNone(m['collective_coverage'])
        self.assertTrue(all(v['value'] is None and v['n']==0 for v in m['averages'].values()))

    def test_empty_and_self_only_graphs_have_no_fabricated_denominators(self):
        self.assertTrue(all(v is None for v in graph_metrics(graph('',[]),{})['values'].values()))
        m=graph_metrics(graph('a',[('a','a')]),evidence(0))
        self.assertEqual(m['values']['components'],1)
        self.assertEqual(m['values']['average_degree'],0)
        self.assertIsNone(m['values']['density'])
        self.assertIsNone(m['values']['modularity'])


class GraphMetricScopeTests(unittest.TestCase):
    setUp=fixtures.ProfessorTests.setUp
    new_client=fixtures.ProfessorTests.new_client
    post=fixtures.ProfessorTests.post
    command=fixtures.ProfessorTests.command

    def test_scope_delivers_class_and_selected_student_after_evidence_update(self):
        state=self.command('start')
        self.command('answer',state,text='Water enters soil.')
        self.post('students',dict(name='Unassessed learner'))
        response=self.client.get('/api/professor/scope',params={'student_id':self.student})
        self.assertEqual(response.status_code,200,response.text)
        data=response.json()
        self.assertEqual(data['selected']['graph_metrics']['values']['relationship_coverage'],100)
        self.assertEqual(data['analytics']['averages']['relationship_coverage']['value'],50)
        self.assertEqual(data['analytics']['students'],2)
        self.assertEqual(data['analytics']['reference']['total'],1)


if __name__=='__main__':
    unittest.main()
