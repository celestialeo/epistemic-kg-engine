# Representative Background Integration Examples

## Purpose

These examples are aligned to the final filtered integration run and are intended to support the report by showing where selective background knowledge:
- clearly improved fidelity
- remained neutral after filtering
- or still caused some semantic drift

They are drawn from:
- `outputs/testpack_v1_graph_fidelity_doc_only.json`
- `outputs/testpack_v1_graph_fidelity_with_background.json`

## 1. Strong Improvement on an Abbreviation-Heavy Scientific Chunk

### Chunk
`tp_0016`  
`definition`

### Original
`Abbrev-heavy: NMDA receptors contribute to plasticity; Ca2+ influx can trigger downstream signaling.`

### Result
- doc_only embedding: `0.6547`
- with_background embedding: `0.8531`
- delta: `+0.1984`

### Interpretation
This is one of the clearest gains in the final run. The document-only version collapses into a generic neuron description, while the background-supported version stays much closer to the source concepts of NMDA receptors, plasticity, and downstream signaling.

## 2. Strong Improvement on a Tool-Oriented Example Chunk

### Chunk
`tp_0018`  
`example`

### Original
`Example: LangChain calls an LLM (Ollama/OpenAI) to output structured JSON that we validate with Pydantic.`

### Result
- doc_only embedding: `0.7537`
- with_background embedding: `0.8641`
- delta: `+0.1104`

### Interpretation
This chunk shows that background support can help when the source content is concept-rich and process-oriented. The background-integrated reconstruction remains more semantically anchored to the original pipeline of LangChain, LLM output, and Pydantic validation.

## 3. A Case Where Background Knowledge Still Hurt

### Chunk
`tp_0001`  
`definition`

### Original
`Claim: Action potentials propagate along an axon when depolarization crosses a threshold and voltage-gated sodium channels open.`

### Result
- doc_only embedding: `0.7999`
- with_background embedding: `0.7278`
- delta: `-0.0721`

### Interpretation
This is a useful reminder that background support is not uniformly beneficial. In this case, the background-integrated version became more generic and lost some of the important causal detail present in the source chunk.

## 4. Metadata After Selective Filtering

### Chunk
`tp_0005`  
`metadata`

### Original
`Metadata: Lab notes, version 0.1. Updated 2026-02-06. Source: practicum testpack.`

### Result
- doc_only embedding: `0.5277`
- with_background embedding: `0.5277`
- delta: `0.0000`

### Interpretation
This example illustrates one of the main improvements in the final setup. Earlier integration attempts could actively harm metadata-like chunks. After selective filtering, metadata remained neutral rather than degrading further, which supports the decision to disable background enrichment for weak chunk types.

## Main Takeaway

The representative examples support the final quantitative result:
- background knowledge helps most on content-bearing chunks such as definitions and examples
- the strongest gains appear when source chunks contain conceptually rich content
- some drift still remains on certain chunks
- metadata is no longer being actively harmed after selective filtering

This supports using background knowledge as a selective semantic support layer rather than a blanket addition to every chunk.
