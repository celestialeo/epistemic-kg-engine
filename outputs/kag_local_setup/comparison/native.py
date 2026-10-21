"""Call pinned KAG components with a local schema and file graph storage."""
import copy
import json
import locale
import os
from pathlib import Path
import uuid

from .observation import Observer, plain


def prepare(config, root, trace):
    # KAG eagerly imports Chinese date prompts. Windows strftime needs UTF-8
    # character encoding even when the selected experiment language is English.
    if os.name == "nt":
        locale.setlocale(locale.LC_CTYPE, ".UTF-8")
    # A fresh project and checkpoint directory prevent cross-run contamination.
    namespace = "Water" + uuid.uuid4().hex[:10]
    runtime = trace.directory / "kag_project"
    runtime.mkdir()
    model = dict(type="ollama", model=config["model"], base_url=config["ollama_url"],
                 timeout=config["model_timeout"], stream=False, enable_check=False)
    embedding = dict(type="local_ollama", model=config["embedding_model"],
                     base_url=config["ollama_url"], timeout=config["model_timeout"],
                     vector_dimensions=config["embedding_dimensions"], batch_size=1)
    native_config = {
        "project": {"namespace": namespace, "host_addr": None,
                    "language": "en", "biz_scene": "default", "id": None,
                    "checkpoint_path": str(runtime / "ckpt")},
        "openie_llm": model, "chat_llm": model,
        "vectorizer": embedding, "vectorize_model": embedding,
        "log": {"level": "DEBUG"},
        "kag_builder_pipeline": {"chain": {
            "type": "unstructured_builder_chain",
            "reader": {"type": "txt_reader"},
            "splitter": {"type": "length_splitter", "split_length": config["kag_split_length"],
                         "window_length": 0, "strict_length": False},
            "extractor": {"type": "knowledge_unit_extractor", "llm": model,
                          "ner_prompt": {"type": "knowledge_unit_ner"},
                          "triple_prompt": {"type": "knowledge_unit_triple"},
                          "kn_prompt": {"type": "knowledge_unit"}},
            "vectorizer": {"type": "batch_vectorizer", "vectorize_model": embedding,
                           "batch_size": 1},
            "post_processor": {"type": "kag_post_processor"},
            "writer": {"type": "local_graph_writer"}},
            "num_threads_per_chain": 1, "num_chains": 1}}
    config_path = runtime / "kag_config.yaml"
    # JSON is valid YAML. ASCII output also works with upstream locale-based reads.
    config_path.write_text(json.dumps(native_config, indent=2), encoding="utf-8")
    os.chdir(runtime)
    # Avoid inherited server configuration when importing the standalone runner.
    os.environ.pop("KAG_PROJECT_ID", None)
    os.environ.pop("KAG_PROJECT_HOST_ADDR", None)
    # Imports are deliberately late: kag initializes configuration at import time.
    from kag.common.conf import KAG_CONFIG
    KAG_CONFIG.initialize(prod=False, config_file=str(config_path))
    from .local_storage import load_schema
    schema = load_schema(root, namespace, trace)
    required = {"Others", "Chunk", "KnowledgeUnit"}
    if not required <= set(schema):
        raise RuntimeError(f"Local KAG schema is missing {sorted(required - set(schema))}")
    trace.save("artifacts/kag_config.json", native_config)
    trace.emit("schema.loaded", namespace=namespace, types=sorted(schema), storage="local_files")
    # Runtime-only schema objects are not serialized into configuration.
    native_config["local_schema"] = schema
    native_config["generation_options"] = {
        "think": config["think"], "options": {"temperature": 0, "seed": 7,
        "num_ctx": config["context_tokens"], "num_predict": config["max_output_tokens"]}}
    return native_config


def components(native_config, trace):
    from .local_embeddings import LocalOllamaVectorizer  # Register local client lifecycle.
    from kag.interface import ReaderABC, SplitterABC, ExtractorABC, VectorizerABC, PostProcessorABC, SinkWriterABC
    spec = native_config["kag_builder_pipeline"]["chain"]
    from .local_storage import schema_bindings, storage_components
    classes = {"reader": ReaderABC, "splitter": SplitterABC, "extractor": ExtractorABC,
               "vectorizer": VectorizerABC}
    with schema_bindings(native_config["local_schema"]):
        built = {name: cls.from_config(copy.deepcopy(spec[name])) for name, cls in classes.items()}
        built["post_processor"], built["writer"] = storage_components(trace)
    observer = Observer(trace, native_config["generation_options"])
    llm = built["extractor"].llm
    llm.client = observer.sync_client(llm.client)
    llm.aclient = observer.async_client(llm.aclient)
    from .local_generation import bind_formats
    bind_formats(built["extractor"], trace)
    vector_model = built["vectorizer"].vectorize_model
    vector_model.aclient = observer.async_client(vector_model.aclient)
    trace.emit("kag.components_ready", components={name: type(value).__name__ for name, value in built.items()},
               generation_options=native_config["generation_options"], storage="local_files")
    return built, observer


def close_components(built):
    """Release checkpoint files so completed runs are movable on Windows."""
    for component in built.values():
        if getattr(component, "_checkpointer_initialized", False):
            checkpointer = component.checkpointer
            if checkpointer is not None:
                checkpointer.close()
    vectorizer = built.get("vectorizer")
    if vectorizer is not None:
        vectorizer.vectorize_model.close()


def invoke(component, data, stage, trace, chunk_id=None):
    request = trace.emit("kag.component.request", entity_id=chunk_id,
                         component=type(component).__name__, operation=stage, input=plain(data))
    # Invoke upstream's public method and unwrap only its transport container.
    # A unique run cache is configured; no prior run's results are reused.
    try:
        wrapped = component.invoke(data)
        output = [item.data for item in wrapped]
    except Exception as exc:
        trace.emit("kag.component.failed", entity_id=chunk_id, parent_id=request,
                   component=type(component).__name__, error=str(exc))
        raise
    trace.emit("kag.component.response", entity_id=chunk_id, parent_id=request,
               component=type(component).__name__, output=plain(output))
    return output


def read_chunks(built, path, text, trace):
    documents = invoke(built["reader"], str(path), "reader", trace)
    native_chunks = []
    for document in documents:
        native_chunks.extend(invoke(built["splitter"], document, "splitter", trace))
    # Restore source whitespace for evaluation only; do not modify KAG's chunks.
    # With zero overlap, concatenated non-whitespace characters must match exactly.
    offsets = [i for i, char in enumerate(text) if not char.isspace()]
    compact = "".join(text[i] for i in offsets)
    position = 0
    chunks = []
    for index, chunk in enumerate(native_chunks):
        fragment = "".join(chunk.content.split())
        if not fragment or compact[position:position + len(fragment)] != fragment:
            raise ValueError("KAG chunks do not cover the source sequentially without overlap; "
                             "refusing to score an altered reference document")
        start = offsets[position]
        position += len(fragment)
        end = offsets[position - 1] + 1
        source = text[start:end]
        chunks.append({"id": f"chunk_{index + 1:03d}", "order": index, "text": source,
                       "start": start, "end": end, "word_count": len(source.split()),
                       "kag_chunk_id": chunk.id,
                       "previous_id": chunks[-1]["id"] if chunks else None})
    if position != len(compact) or " ".join(text.split()) != " ".join(
            " ".join(row["text"] for row in chunks).split()):
        raise ValueError("KAG chunking lost, duplicated, or split source words; no comparable score")
    trace.save("artifacts/kag_chunks.json", [chunk.to_dict() for chunk in native_chunks])
    trace.save("artifacts/chunks.json", chunks)
    return native_chunks, chunks


def construct(built, observer, native_chunks, chunks, trace):
    snapshots = []
    for chunk, row in zip(native_chunks, chunks):
        observer.chunk_id = row["id"]
        print(f"  KAG constructing {row['id']}", flush=True)
        flow = [chunk]
        for stage in ("extractor", "vectorizer", "post_processor", "writer"):
            result = []
            for item in flow:
                result.extend(invoke(built[stage], item, stage, trace, row["id"]))
            flow = result
            if not flow:
                raise RuntimeError(f"KAG {stage} returned no subgraph for {row['id']}")
            trace.save(f"artifacts/kag/{row['id']}/{stage}.json", [graph.to_dict() for graph in flow])
        for graph in flow:
            snapshots.append({"chunk_id": row["id"], "kag_chunk_id": chunk.id,
                              "graph": graph.to_dict()})
        trace.save("artifacts/kag_graph_progress.json", snapshots)
    observer.chunk_id = None
    trace.save("artifacts/kag_graph.json", {"format": "KAG subgraphs persisted to local files",
               "storage": "local_files", "subgraphs": snapshots})
    trace.save("artifacts/kag_model_issues.json", observer.issues)
    return snapshots
