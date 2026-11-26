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

## Archived inputs

All other input documents are stored in the root [archive/inputs](../archive/inputs/):

- `input.txt`
- `sample.txt`
- `water_cycle.txt`
- `water_cycle_sample.txt`
- `AI Chapter.txt`
- `Neurology Chapter.txt`
- `validation/` (test fixtures and expected claims)

The previous input descriptions and background-reading links are preserved in
[previous-input-catalog.md](../archive/inputs/previous-input-catalog.md). It is a historical
catalog; paths in it describe the layout before archiving.

To run an archived document, use its explicit archive path, for example
`--input "archive/inputs/input.txt"`. The old neuroscience/water-cycle `--chapter`
aliases (including `both`) remain legacy embedded notebook examples. Specify an
active input explicitly when running the pipeline.

The latest November 25 graph for each active input is listed in
[outputs/runs/README.md](../outputs/runs/README.md). All historical inputs, runs,
database backups, and generated diagnostics share the root [archive](../archive/).
