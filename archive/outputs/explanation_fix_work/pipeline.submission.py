from .settings import setting
from .settings import automatic_chunk_words
"""Notebook execution modes; no model inference occurs unless explicitly selected."""
from datetime import datetime
import hashlib
import html
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
import _submission_runtime as runtime

_server_state = None


def load_saved(directory):
    """Read available checkpoints without executing or modifying a saved run."""
    directory = Path(directory).resolve()
    if not directory.is_dir():
        raise FileNotFoundError(directory)
    names = ["manifest.json", "statistics.json", "artifacts/paragraphs.json",
             "artifacts/chunks.json", "artifacts/extractions.json", "artifacts/chapter_outline.json",
             "artifacts/concepts.json", "artifacts/relations.json", "artifacts/seeds.json",
             "artifacts/debate.json", "artifacts/graph.json", "artifacts/evaluation.json",
             "artifacts/environment.json"]
    artifacts, missing, warnings = {}, [], []
    for name in names:
        path = directory / name
        if path.is_file():
            artifacts[name] = json.loads(path.read_text(encoding="utf-8"))
        else:
            missing.append(name)
    manifest = artifacts.get("manifest.json", {})
    checked = 0
    for name, expected in manifest.get("artifacts", {}).items():
        path = (directory / name).resolve()
        if not path.is_relative_to(directory):
            warnings.append(f"Rejected artifact path outside run: {name}")
        elif not path.is_file():
            warnings.append(f"Manifest artifact missing: {name}")
        elif expected.get("sha256"):
            checked += 1
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected["sha256"]:
                warnings.append(f"Hash mismatch: {name}")
    if not manifest.get("artifacts"):
        warnings.append("No manifest artifact hashes available; integrity is unverified")
    return dict(directory=str(directory), artifacts=artifacts, missing=missing,
                warnings=warnings, hashes_checked=checked)


def results_table(saved):
    artifacts = saved["artifacts"]
    manifest = artifacts.get("manifest.json", {})
    evaluation = artifacts.get("artifacts/evaluation.json", {})
    graph = artifacts.get("artifacts/graph.json", {})
    environment = artifacts.get("artifacts/environment.json", {})
    rows = {
        "Source directory": saved["directory"],
        "Run ID": manifest.get("run_id"), "Run status": manifest.get("status"),
        "Evaluation status": evaluation.get("status"),
        "Saved document score / 100": evaluation.get("final_score"),
        "Metric version": evaluation.get("metric_version"),
        "Nodes": len(graph["nodes"]) if "nodes" in graph else None,
        "Edges": len(graph["edges"]) if "edges" in graph else None,
        "Unresolved items": len(manifest["unresolved_items"]) if "unresolved_items" in manifest else None,
        "Configuration": manifest.get("config"), "Model details": environment.get("model_details"),
        "Verified artifact hashes": saved["hashes_checked"],
        "Missing artifacts": saved["missing"], "Integrity warnings": saved["warnings"],
    }
    return "<table><caption>Saved values only; not rerun or independently verified</caption>" + "".join(
        "<tr><th>" + html.escape(key) + "</th><td>" + html.escape(str(value)) + "</td></tr>"
        for key, value in rows.items()) + "</table>"


def offline_checks():
    """Synthetic deterministic checks, explicitly not empirical model results."""
    from .ingest import split_document
    from .trace import Trace
    from .graph_view import render_graph
    from .evaluation import metrics, ClaimMatch
    text = "Water evaporates.\n\nVapor condenses."
    with tempfile.TemporaryDirectory() as directory:
        trace = Trace(Path(directory) / "offline", "synthetic-offline")
        try:
            paragraphs, chunks = split_document(text, automatic_chunk_words(text), trace)
            assert len(paragraphs) == len(chunks) == 2
            assert all(text[c["start"]:c["end"]] == c["text"] for c in chunks)
            page = render_graph(dict(run_id="synthetic-empty-graph", nodes=[], edges=[]))
            assert "__GRAPH_DATA__" not in page and "<html" in page.lower()
            scores = metrics("Water evaporates.", "Water evaporates.", ["synthetic"], ["synthetic"],
                             [ClaimMatch(original_index=0, reconstructed_index=0, reason="Synthetic identity check")])
            assert scores["final_score"] == 100
        finally:
            trace.close()
    return dict(kind="synthetic software checks; no model calls", paragraphs=2, chunks=2,
                offsets_preserved=True, empty_graph_rendered=True,
                identity_metric_check=scores["final_score"])


def stop_server():
    global _server_state
    if _server_state is None:
        return
    server, worker, sock, url = _server_state
    server.should_exit = True
    worker.join(timeout=setting('operations', 'server_stop_seconds'))
    if worker.is_alive():
        raise RuntimeError("Server is still stopping; wait for active requests before retrying")
    sock.close()
    _server_state = None


def start_server(app, *, port=0, route=""):
    """Run uvicorn in a managed thread so a notebook's event loop stays usable."""
    import uvicorn
    global _server_state
    if not 0 <= port <= 65535:
        raise ValueError("port must be between 0 and 65535")
    stop_server()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", port))
        sock.listen(setting('operations', 'server_backlog'))
        url = f"http://127.0.0.1:{sock.getsockname()[1]}{route}"
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
        worker = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        _server_state = server, worker, sock, url
        worker.start()
        deadline = time.monotonic() + setting('operations', 'server_start_seconds')
        while not server.started and worker.is_alive() and time.monotonic() < deadline:
            time.sleep(setting('operations', 'server_poll_seconds'))
        if not server.started:
            stop_server()
            raise RuntimeError("Interactive server did not start")
        return dict(mode="server", url=url, stop="stop_server()", extraction_rerun=False)
    except BaseException:
        sock.close()
        raise


def execute(mode="offline", *, saved_run=None, pipeline_args=None, stage_args=None,
            runs_root=None, port=0, input_path=None, database=None):
    pipeline_args, stage_args = list(pipeline_args or []), list(stage_args or [])
    runs_root = Path(runs_root) if runs_root is not None else runtime.root / "outputs/runs"
    if mode in {"background", "refine", "evaluate", "render", "graph"} and saved_run is None:
        raise ValueError(f"{mode} requires SAVED_RUN pointing to an existing saved run")
    if mode == "offline":
        return offline_checks()
    if mode == "ingest":
        from .ingest import split_document
        from .trace import Trace
        path = Path(input_path) if input_path else runtime.root / "data/ai_test.txt"
        text = runtime.input_bytes(path).decode("utf-8-sig")
        with tempfile.TemporaryDirectory() as directory:
            trace = Trace(Path(directory) / "ingest", "ingest-only")
            try:
                paragraphs, chunks = split_document(text, automatic_chunk_words(text), trace)
            finally:
                trace.close()
        return dict(mode=mode, paragraphs=paragraphs, chunks=chunks, inference=False)
    if mode == "full":
        from .cli import main
        if "--interact" in pipeline_args:
            raise ValueError("Choose MODE='interact' or MODE='graph' for notebook servers")
        # Servers cannot own the notebook's already-running asyncio loop.
        for flag in ("--no-open", "--no-explorer"):
            if flag not in pipeline_args:
                pipeline_args.append(flag)
        return dict(mode=mode, exit_code=main(pipeline_args))
    if mode == "background":
        from .replay_background import main
        return dict(mode=mode, result=main([str(saved_run), *stage_args]), scope="background and graph only")
    if mode == "refine":
        from .graph_quality import main
        return dict(mode=mode, exit_code=main([str(saved_run), *stage_args]))
    if mode == "evaluate":
        from .evaluate_saved_run import main
        return dict(mode=mode, exit_code=main([str(saved_run), *stage_args]))
    if mode == "render":
        from .graph_view import render_graph
        from IPython.display import HTML, display
        # Iframe isolates the viewer's DOM and JavaScript from Jupyter's page.
        graph = json.loads((Path(saved_run) / "artifacts/graph.json").read_text(encoding="utf-8"))
        page = render_graph(graph)
        display(HTML('<iframe sandbox="allow-scripts" style="width:100%;height:650px;border:0" srcdoc="'
                     + html.escape(page, quote=True) + '"></iframe>'))
        return dict(mode=mode, inference=False, nodes=len(graph["nodes"]), edges=len(graph["edges"]))
    if mode == "graph":
        from .explorer import create_app
        return start_server(create_app([Path(saved_run)]), port=port)
    if mode in {"interact", "professor"}:
        from .explorer import create_app, load_snapshot
        from .professor import discover_latest, run_identity, topic_identity
        from .student_store import StudentStore
        selected = None
        if mode == "interact":
            if saved_run is not None:
                selected = load_snapshot(saved_run)
            else:
                snapshots, warnings = discover_latest(runs_root)
                for warning in warnings:
                    print(warning)
                if not snapshots:
                    raise ValueError("No completed saved runs; select SAVED_RUN or generate a run first")
                selected = max(snapshots, key=lambda s: (
                    datetime.fromisoformat((s.manifest.get("started_at_utc") or s.manifest["started_at"]).replace("Z", "+00:00")).timestamp(),
                    s.directory.name))
        store = StudentStore(Path(database) if database else runtime.root / "outputs/professor/students.sqlite3")
        route = "/professor"
        if selected is not None:
            identifier = run_identity(selected)
            key, title = topic_identity(selected)
            store.register_run(identifier, key, title, selected)
            route += "?run=" + identifier
        return start_server(create_app([], professor_store=store, runs_root=runs_root), port=port, route=route)
    raise ValueError(f"Unknown execution mode: {mode}")
