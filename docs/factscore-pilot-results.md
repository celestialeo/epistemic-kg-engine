# First FActScore comparison pilot

Date: 2026-09-20. This is a live local-model pilot, not a synthetic test fixture.

The implementation completed a before/after comparison of two chunks and two
background edges from `run_20260914_174040_72ef4ce6`. It demonstrates that evidence
filtering, reconstruction evaluation, statistics, and graph comparison work
together. **It does not establish a general improvement in factual accuracy.**

The experiment is saved in:

`outputs/runs/run_20260914_174040_72ef4ce6/factscore/compare_20260920_180004_ac2ef174/`

- [Interactive graph comparison](../outputs/runs/run_20260914_174040_72ef4ce6/factscore/compare_20260920_180004_ac2ef174/graph_comparison.html)
- [Statistical report and claim audit](../outputs/runs/run_20260914_174040_72ef4ce6/factscore/compare_20260920_180004_ac2ef174/report.html)
- [Generated Markdown report](../outputs/runs/run_20260914_174040_72ef4ce6/factscore/compare_20260920_180004_ac2ef174/report.md)

These output links are local; generated runs are excluded from Git.

## Setup

Both arms used `llama3.2:3b` for generation and claim verification and
`nomic-embed-text` for similarity, with temperature 0 and seed 7. The baseline
used the original document hints and the selected original approved background
edges. The after arm required all checked claims of an edge to have evidence
support. The full input document supplied the reference passages; no independent
external references were supplied.

The pilot selected the first two saved evaluation chunks and the two
highest-ranked eligible edges before checking evidence. These were prerequisite
relationships from action potential to threshold and from axon to action
potential. Both edges failed the source-support check and were removed. The
original run and its reports were preserved.

## Observed results

| Metric | Baseline mean | After mean | Paired change | 95% bootstrap interval for change |
| --- | ---: | ---: | ---: | --- |
| Embedding similarity | 0.8692 | 0.9523 | +0.0831 | 0.0000 to +0.1663 |
| Lexical similarity | 0.4892 | 0.5854 | +0.0962 | 0.0000 to +0.1924 |
| Estimated source claim precision | 0.1667 | 0.1667 | 0.0000 | 0.0000 to 0.0000 |
| Estimated original claim coverage | 0.2500 | 0.4167 | +0.1667 | 0.0000 to +0.3333 |
| Estimated claim F1 | 0.2000 | 0.2000 | 0.0000 | 0.0000 to 0.0000 |

Each row uses two matched chunks. One chunk was unchanged; the other improved
in similarity and estimated coverage. For those changed metrics, the paired
t-test p-value was 0.50 and the Wilcoxon p-value was 1.00. The sample is too small
to support an improvement claim. The intervals describe this two-chunk sample,
not uncertainty over new documents.

Four background claims were checked and none received support. The after graph
has zero retained background edges in this pilot, so its background precision
is **undefined**, not 100%. This provides no estimate of externally verified
background accuracy or recall.

The run finished in approximately 332 seconds with 37 uncached model operations,
12 cache hits, and no API/schema/citation-validation errors. The model operations
include generation, verification, decomposition, and embeddings; the count does
not count each retry separately.

## Interpretation and limitations

Removing prerequisite hints helped the action-potential reconstruction stay
closer to the source rather than describe what a student should understand.
This is an example of potentially useful filtering, not evidence that every
removed edge was false. Ordinary reference text may not establish pedagogical
prerequisite claims.

The verifier's judgments also need validation. For example, it labeled
"A neuron transmits signals" unsupported by a source that describes a neuron
transmitting information using electrical and chemical signals. This is a
questionable rejection of a close paraphrase. The low absolute precision and
coverage scores should therefore not be treated as reliable measurements of
the graph's true factual quality. Citation-format validation cannot catch such
semantic judgment errors.

Before drawing research conclusions, supply a separate reference collection,
manually label a sample of claims, evaluate the verifier against those labels,
and compare multiple documents with the full edge sets. An alternative verifier
can be selected with `--factscore-verifier MODEL_NAME` without changing the
baseline generator. The [comparison guide](factscore-comparison.md) provides
commands, evidence format, and detailed metric definitions.
