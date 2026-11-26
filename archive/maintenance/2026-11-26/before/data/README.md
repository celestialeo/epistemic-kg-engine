# Chapter inputs

The five active input documents are:

| File | Content |
| --- | --- |
| `llm_tuning.txt` | Foundation LLMs, fine-tuning, and distillation. |
| `neurons_and_glia.txt` | Neurons and glia. |
| `ai_test.txt` | Short, three-sentence AI test. Also available as `--chapter ai-test`. |
| `AI Chapter.txt` | AI chapter covering transformers, training, and retrieval. |
| `Neurology Chapter.txt` | Neural pathways, synapses, glia, myelin, and reflex circuits. |

Run any active input from the project root using its filename:

```powershell
& .\.venv\Scripts\python.exe .\run_pipeline.py --input "data/llm_tuning.txt"
```

Source links for `llm_tuning.txt` and `neurons_and_glia.txt` are recorded separately
in [input_sources.txt](input_sources.txt). `llm_tuning.txt` is unchanged from the
supplied local file. `neurons_and_glia.txt` is a concise paraphrase of the replacement
BrainFacts article, using plain paragraphs and omitting webpage clutter.
These links document input provenance; they are not automatically retrieved
evidence for generated background facts.

## Archived inputs

The following documents were moved unchanged into `data/archive/`:

- `input.txt`
- `sample.txt`
- `water_cycle.txt`
- `water_cycle_sample.txt`

The previous input descriptions and background-reading links are preserved in
[previous-input-catalog.md](archive/previous-input-catalog.md). It is a historical
catalog; paths in it describe the layout before archiving.

To run an archived document, use its explicit archive path, for example
`--input "data/archive/input.txt"`. The old neuroscience/water-cycle `--chapter`
aliases (including `both`) still refer to the former paths and should not be used
with this layout. Specify an active input explicitly when running the pipeline.

The `validation/` folder contains test fixtures, not active chapter inputs.
