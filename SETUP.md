# Project setup and running guide

This project turns text into knowledge graphs and provides a local workspace for exploration, quizzes, and student progress. Start with the saved graphs before generating your own.

The implementation lives in `261273237.ipynb`. Keep that notebook in the project root alongside `run_pipeline.py`, even when using only the terminal commands.

## Requirements

| Component | What you need |
| --- | --- |
| Python | **Python 3.12 is the recommended version** used for project validation. Terminal dependencies support 3.10+; the pinned notebook dependencies require 3.11+. |
| Operating system | The commands below use Windows PowerShell. Ollama supports [Windows 10 22H2 or newer](https://docs.ollama.com/windows), [macOS 14 or newer](https://docs.ollama.com/macos), and [Linux](https://docs.ollama.com/linux). |
| Browser | A current browser such as Chrome, Edge, or Firefox for the local interface. |
| Model service | Install [Ollama](https://ollama.com/download) separately from Python. Use a current version that supports `qwen3.5:9b`. |
| Models | `qwen3.5:9b` handles language tasks; `nomic-embed-text` generates embeddings used for matching and retrieval. |
| Internet | Needed initially to download Python packages, Ollama, and models. The configured local inference backend does not require a cloud API key. |

### Hardware for local model inference

Allow **16–32 GB of system RAM**, with **32 GB preferable**, and roughly **20–30 GB of free SSD space** for software, models, and initial results. These are planning estimates, not tested minimums. Model downloads take several gigabytes; see the [Qwen package](https://ollama.com/library/qwen3.5:9b) and [embedding model](https://ollama.com/library/nomic-embed-text).

A supported GPU improves inference speed. **12–16 GB of GPU memory is a useful planning target** for the default 9B model at moderate context sizes; actual needs vary. Apple Silicon uses shared memory. CPU-only execution can be slow. Check [Ollama hardware compatibility](https://docs.ollama.com/gpu) and install compatible drivers.

Opening saved graphs and reading stored results does not require loading a model. Generating graphs, semantic matching, question generation, and grading do.

## 1 Prepare the Python environment

Extract the project ZIP or clone the repository, then open PowerShell **inside the project root**. Keep `data/` and any supplied `outputs/runs/` folders with the project. The `archive/` folder is unnecessary for normal use.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-notebook.txt
```

`requirements-notebook.txt` installs the application dependencies and Jupyter. For terminal use without Jupyter, install `requirements.txt` instead. The commands use the environment's Python directly, so activation is unnecessary.

On macOS or Linux, create the environment with `python3.12 -m venv .venv` and replace the Windows Python path in the examples with `.venv/bin/python`.

## 2 Install and check the models

Install Ollama, start its application or service, and open a fresh terminal so the `ollama` command is available. Download both models:

```powershell
ollama pull qwen3.5:9b
ollama pull nomic-embed-text
ollama list
ollama run qwen3.5:9b "Reply with one short sentence."
```

The final command checks that the language model loads and responds. The Python `ollama` package supplies the client; the service and model downloads are separate installations.

The default connection is `http://127.0.0.1:11434`. If needed, start the Ollama application or run `ollama serve` in another terminal. Use an existing Ollama service if that port is already occupied.

## 3 Open the saved project

```powershell
.\.venv\Scripts\python.exe -m pipeline.professor --runs-root outputs/runs --database outputs/professor/students.sqlite3 --no-open
```

Open the printed URL and keep the terminal running; **Ctrl+C** stops the server. The tabs are **Quiz**, **Run Insights**, and **Class Overview**. Saved runs open without rerunning extraction. Leave Ollama running for model-powered features.

Git excludes the local student database, so a fresh checkout can have an empty roster. A project ZIP may include existing records. Preserve `outputs/professor/students.sqlite3` and run-local `manual_graph.sqlite3` files when transferring progress and graph edits.

## 4 Generate a new graph

Start with the small supplied input:

```powershell
.\.venv\Scripts\python.exe run_pipeline.py --input data/ai_test.txt --no-open --no-explorer
```

Replace the input with your own UTF-8 text file; blank lines separate paragraphs. Extraction, review, background expansion, graph construction, and evaluation make many model calls. Larger documents can take substantial time.

Results go under `outputs/runs/`. Check the report for unresolved issues, then restart the workspace to load the run. `--no-open --no-explorer` finishes generation without launching a browser or server.

## 5 Use the notebook if preferred

```powershell
.\.venv\Scripts\python.exe -m notebook 261273237.ipynb
```

Select the `.venv` kernel. With the default `MODE = "offline"`, **Restart and Run All** runs a synthetic demonstration without inference. After configuring Ollama, use `MODE = "professor"` for the workspace or `MODE = "full"` for generation using `PIPELINE_ARGS`. Notebook servers stop when the kernel exits.

## Settings and optional components

- **Connection:** Local defaults need no `.env` file. For another Ollama address, set `OLLAMA_HOST` using the environment or a private `.env`; `.env.example` shows the format.
- **Model budgets:** `pipeline_settings.json` currently defaults to an 8,192-token context, a 4,096-token output ceiling, and a 600-second request timeout. CLI options such as `--context-tokens` and `--model-timeout` override these for a new run. Saved-run interactions can reuse that run's recorded settings.
- **Memory:** Longer contexts require more memory. Check `ollama ps` while a model is loaded to see CPU/GPU placement. Increase context only when the task needs it and hardware allows it; see [Ollama context guidance](https://docs.ollama.com/context-length).
- **Neo4j and Docker:** Optional for graph export. The standard interface uses saved files and SQLite. For Docker-based export, install Docker with Compose, configure `NEO4J_PASSWORD` in `.env`, and add `--start-neo4j` to a generation command. The supplied `compose.yaml` starts Neo4j.

## Common setup problems

| Problem | First check |
| --- | --- |
| Python package is missing | Run installation and launch commands with the same `.venv` Python. |
| Ollama cannot be reached or model is missing | Start Ollama, check `OLLAMA_HOST`, run `ollama list`, and pull the exact required model name. |
| Very slow calls or insufficient memory | Check `ollama ps`, close other memory-heavy applications, and review the context size. Switching models can change output quality and grading behavior. |
| Context limit or timeout errors | Start with the small input. Increase the relevant budget only if hardware allows; a longer timeout does not resolve insufficient memory. |
| No saved graphs appear | Confirm `outputs/runs/` is present or generate a graph first. Use the printed URL and correct runs directory. |

See [README.md](README.md) for advanced commands and [docs/professor.md](docs/professor.md) for the interface and assessment workflow.
