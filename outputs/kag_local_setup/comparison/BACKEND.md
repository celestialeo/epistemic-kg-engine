# Local storage

The water-cycle runner uses `storage: local_files` in `comparison/config.json`.
It needs only Python and local Ollama. No OpenSPG backend or Docker is required.

Schema definitions are loaded locally; graph snapshots, model calls, reconstructed
text and scores are saved under `outputs/runs/water-cycle-simplified/`.

`prepare_water_backend.ps1` is retained as a historical optional deployment helper.
It is not called by setup or the runner and is unnecessary for this experiment.
See [README.md](README.md) for the pipeline, local adaptations and output contract.
