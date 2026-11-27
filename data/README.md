# Chapter inputs

The three active input documents are:

| File | Content |
| --- | --- |
| `llm_tuning.txt` | Foundation LLMs, fine-tuning, and distillation. |
| `neurons_and_glia.txt` | Neurons and glia. |
| `ai_test.txt` | Short, three-sentence AI test. Also available as `--chapter ai-test`. |

Run any active input from the project root using its filename:

```powershell
& .\.venv\Scripts\python.exe .\run_pipeline.py --input "data/llm_tuning.txt" --output-root "outputs/runs/llm-tuning" --context-tokens 24576 --no-model-cache
```

Source links for `llm_tuning.txt` and `neurons_and_glia.txt` are recorded separately
in [input_sources.txt](input_sources.txt). `llm_tuning.txt` is unchanged from the
supplied local file. `neurons_and_glia.txt` is a concise paraphrase of the replacement
BrainFacts article, using plain paragraphs and omitting webpage clutter.
These links document input provenance; they are not automatically retrieved
evidence for generated background facts.

## Test inputs

The sample document used by the ingestion tests is in
[tests/fixtures/sample.txt](../tests/fixtures/sample.txt). The two three-paragraph
validation documents and their expected-claims checklist are in
[tests/fixtures/validation](../tests/fixtures/validation/).

Historical input archives are no longer bundled with the project. The old
neuroscience/water-cycle `--chapter` aliases (including `both`) remain legacy
embedded notebook examples. Specify an active input explicitly when running the pipeline.

The latest November 25 graph for each active input is listed in
[outputs/runs/README.md](../outputs/runs/README.md).
