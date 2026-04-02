# Team Sync Brief

## Goal of the Meeting

The goal of this meeting is to:
- align the document-graph work and the background-knowledge work
- decide the integration boundary between both parts
- agree on one concrete experiment to complete this week

## What I Have Built So Far

So far, I have built:
- a document-grounded knowledge graph pipeline from chunked instructional text
- concept extraction, mention building, Neo4j loading, and retrieval
- a graph-fidelity validation layer that regenerates text from the graph and compares it back to the original chunk
- comparison and hypothesis-testing scripts to evaluate different graph strategies

## Main Result So Far

The main result from my current experiments is:
- the concept-only graph is currently the strongest honest baseline
- the current relation layer is not yet improving regeneration fidelity consistently
- the main bottleneck appears to be graph representation quality, especially concept quality and chunk coverage

## How My Teammate's Work Fits Into This

I see the two workstreams connecting in a clean way:
- my side builds the **document graph**
- Michel's side builds the **background/prerequisite graph**
- together, the combined graph should support:
  - better retrieval
  - better learner-facing explanations
  - better semantic coverage than the document graph alone

## Best Integration Point

The cleanest connection point seems to be:

1. I build cleaned document concepts from chunked text.
2. I choose seed concepts from that cleaned concept graph.
3. Michel expands those seeds with background knowledge.
4. We load the approved background edges into Neo4j.
5. Finally test whether the combined graph improves retrieval or regeneration.

So the shared boundary should be:

**cleaned document concepts -> background expansion pipeline**

## File-to-File Integration Map

The most practical integration flow using the current repo is:

1. [langchain_extract_knowledgeunits.py](/home/miggy/Practicum%20Project-%202026/src/langchain_extract_knowledgeunits.py)  
   Input: `outputs/testpack_v1_chunks.json`  
   Output: `outputs/testpack_v1_extractions.json`

2. [build_mentions_from_extractions.py](/home/miggy/Practicum%20Project-%202026/src/build_mentions_from_extractions.py)  
   Input: `outputs/testpack_v1_extractions.json`  
   Output:
   - `outputs/testpack_v1_concepts_dedup.json`
   - `outputs/testpack_v1_mentions.json`

3. [load_concepts_to_neo4j.py](/home/miggy/Practicum%20Project-%202026/src/load_concepts_to_neo4j.py)  
   Input: `outputs/testpack_v1_concepts_dedup.json`  
   Output: cleaned document concepts loaded into Neo4j

4. [load_mentions_to_neo4j.py](/home/miggy/Practicum%20Project-%202026/src/load_mentions_to_neo4j.py)  
   Input: `outputs/testpack_v1_mentions.json`  
   Output: chunk-to-concept graph loaded into Neo4j

5. [select_seed_concepts.py](/home/miggy/Practicum%20Project-%202026/src/select_seed_concepts.py)  
   Input: current Neo4j concept graph  
   Output: `outputs/seed_concepts.json`

6. [expand_background_knowledge.py](/home/miggy/Practicum%20Project-%202026/src/expand_background_knowledge.py)  
   Input: `outputs/seed_concepts.json`  
   Output: `outputs/background_candidates.json`

7. [score_background_candidates.py](/home/miggy/Practicum%20Project-%202026/src/score_background_candidates.py)  
   Input: `outputs/background_candidates.json`  
   Output: `outputs/background_approved.json`

8. [load_background_to_neo4j.py](/home/miggy/Practicum%20Project-%202026/src/load_background_to_neo4j.py)  
   Input: `outputs/background_approved.json`  
   Output: background edges loaded into Neo4j

9. [evaluate_graph_fidelity.py](/home/miggy/Practicum%20Project-%202026/src/evaluate_graph_fidelity.py)  
   Input: Neo4j graph after document-only or document+background loading  
   Output:
   - `outputs/testpack_v1_graph_fidelity_full.json`
   - or `outputs/testpack_v1_graph_fidelity_auto_full.json`

10. [compare_fidelity_runs.py](/home/miggy/Practicum%20Project-%202026/src/compare_fidelity_runs.py) and [hypothesis_test_fidelity.py](/home/miggy/Practicum%20Project-%202026/src/hypothesis_test_fidelity.py)  
    Input: fidelity outputs from different graph settings  
    Output: comparison summaries and paired tests


## Important Issue To Discuss

One important issue I want to raise is that the current background outputs still include noisy or weak seed concepts such as:
- `chunk`
- `concept`
- `answer`
- raw `ltp`

This suggests that the background workflow should probably start from the newer cleaned concept set, rather than older noisier seeds.

## Questions 

- Am I generating background knowledge from the latest cleaned concept set, or from older seed exports?
- Should I filter seed concepts before background expansion?
- Which background relation types do I trust most right now?
- Do I want the first combined experiment to target a few neuroscience concepts only, rather than the whole testpack?
- Should I evaluate the combined graph using retrieval quality, regeneration fidelity, or both?

## Best Proposal For This Week

The plan I want to suggest is:

- use the cleaned document concept graph as the seed source
- pick a small set of meaningful concepts such as `neuron`, `synapse`, `hippocampus`, and `long-term potentiation`
- run background expansion only on those concepts first
- load approved background edges into Neo4j
- compare:
  - document graph only
  - document graph + background knowledge
- evaluate whether the combined graph improves support for regeneration or concept-centered retrieval

## What Success Would Look Like By Friday

By Friday, success would mean:
- both sides of the pipeline are connected
- one small combined experiment runs end to end
- We can show whether background knowledge helps, hurts, or is neutral
- We have one clear next engineering question based on the result


