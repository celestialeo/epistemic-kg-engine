"""Local schema and graph persistence for the pinned KAG builder.

Upstream extraction, embedding, postprocessing and writer normalization remain
in use. Only schema lookup and the writer's database transport are replaced.
"""
from contextlib import contextmanager
import importlib


def load_schema(root, namespace, trace):
    from knext.schema.marklang.schema_ml import SPGSchemaMarkLang
    from knext.schema.model.property import Property
    from knext.schema.model.base import IndexTypeEnum
    from kag.indexer.kag_index_manager import KAGIndexManager

    template = root / "kag/templates/schema/{{default}}.schema.tmpl"
    source = template.read_text(encoding="utf-8").replace("{{namespace}}", namespace)
    parsed = SPGSchemaMarkLang("", with_server=False, script_data_str=source)
    types = dict(parsed.types)
    trace.text("artifacts/schema/default.schema", source)
    # Same index definitions and merge order as upstream `knext schema commit`.
    for name in KAGIndexManager.list_available():
        manager = KAGIndexManager.from_config({"type": name, "llm_config": None,
                                              "vectorize_model_config": None})
        if manager.schema:
            source = f"namespace {namespace}\n" + manager.schema
            parsed = SPGSchemaMarkLang("", with_server=False, script_data_str=source)
            types.update(parsed.types)
            trace.text(f"artifacts/schema/{name}.schema", source)
    schema = {name.rsplit(".", 1)[-1]: value for name, value in types.items()}
    # The server normally supplies inherited identity properties from Thing.
    # Define them explicitly for local embedding metadata; no backend is queried.
    for value in schema.values():
        if "name" not in value.properties:
            value.add_property(Property("name", "Text", index_type=IndexTypeEnum.TextAndVector))
        if "id" not in value.properties:
            value.add_property(Property("id", "Text"))
    trace.save("artifacts/kag_schema.json", {
        "storage": "local_files", "namespace": namespace,
        "inherited_properties": {"id": "Text", "name": "TextAndVector"},
        "types": {name: value.to_rest().to_dict() for name, value in schema.items()},
    })
    return schema


@contextmanager
def schema_bindings(schema):
    """Bind only constructors that need a schema, then restore their imports.

This single-threaded CLI does not change the upstream SchemaClient globally.
Every constructed component retains its own in-memory schema afterward.
"""
    from knext.schema.client import SchemaClient

    class LocalSchemaClient(SchemaClient):
        def __init__(self, *args, **kwargs):
            pass

        def load(self):
            return schema

    modules = [importlib.import_module(name) for name in (
        "kag.builder.component.extractor.knowledge_unit_extractor",
        "kag.builder.prompt.default.knowledge_unit_ner",
        "kag.builder.component.vectorizer.batch_vectorizer",
        "kag.builder.component.postprocessor.kag_postprocessor",
    )]
    previous = [(module, module.SchemaClient) for module in modules]
    try:
        for module, _ in previous:
            module.SchemaClient = LocalSchemaClient
        yield
    finally:
        for module, original in previous:
            module.SchemaClient = original


def storage_components(trace):
    from kag.interface import SinkWriterABC
    from kag.builder.component.writer.kg_writer import KGWriter
    from kag.builder.component.postprocessor.kag_postprocessor import KAGPostProcessor

    class FileGraphClient:
        def __init__(self):
            self.count = 0

        def write_graph(self, sub_graph, operation, lead_to_builder=False):
            if operation != "UPSERT" or lead_to_builder:
                raise ValueError("Local graph storage supports snapshot UPSERT only")
            self.count += 1
            path = f"artifacts/kag/writes/graph_{self.count:05d}.json"
            trace.save(path, sub_graph)
            trace.emit("graph.snapshot_written", operation=str(operation), path=path,
                       nodes=len(sub_graph["resultNodes"]), edges=len(sub_graph["resultEdges"]),
                       storage="local_files")

    class LocalGraphWriter(KGWriter):
        def __init__(self):
            SinkWriterABC.__init__(self)
            self.project_id = None
            self.delete = False
            self.client = FileGraphClient()

    class LocalPostProcessor(KAGPostProcessor):
        def _init_search(self):
            if self.similarity_threshold is not None or self.external_graph is not None:
                raise ValueError("Local runs do not support database similarity search")
            self._search_client = None

    return LocalPostProcessor(), LocalGraphWriter()
