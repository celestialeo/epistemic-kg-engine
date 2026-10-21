"""Constrain Ollama responses to the shapes expected by native KAG parsers."""
from contextvars import ContextVar
from functools import wraps

STRING = {"type": "string"}
STRINGS = {"type": "array", "items": STRING}
ENTITY_SCHEMA = {"type": "object", "properties": {
    "Name": STRING, "Category": STRING, "Domain Ontology": STRING,
    "Description": STRING, "Standard Name": STRING, "Synonyms": STRINGS},
    "required": ["Name", "Category", "Domain Ontology", "Description", "Standard Name", "Synonyms"],
    "additionalProperties": False}
UNIT_SCHEMA = {"type": "object", "properties": {
    "Content": STRING, "Knowledge Type": STRING, "Structural Content": STRING,
    "Domain Ontology": STRING, "Core Entities": STRING,
    "Related Query": STRINGS, "Extended Knowledge Points": STRINGS},
    "required": ["Content", "Knowledge Type", "Domain Ontology", "Core Entities",
                 "Related Query", "Extended Knowledge Points"], "additionalProperties": False}
SCHEMAS = {
    "entities": {"type": "array", "items": ENTITY_SCHEMA},
    "knowledge_units": {"type": "object", "additionalProperties": UNIT_SCHEMA},
    "triples": {"type": "array", "items": {
        "type": "array", "items": STRING, "minItems": 4, "maxItems": 4}},
}
CURRENT_RESPONSE = ContextVar("kag_local_response", default=None)


def validate_parsed(role, result):
    if role == "entities":
        valid = isinstance(result, list) and all(
            isinstance(row, dict) and all(isinstance(row.get(k), str) and row[k] for k in ("name", "category"))
            and isinstance(row.get("ontology", ""), str) for row in result)
    elif role == "knowledge_units":
        valid = isinstance(result, dict) and all(
            isinstance(row, dict) and isinstance(row.get("knowledgetype"), str)
            and isinstance(row.get("content"), str) and isinstance(row.get("core_entities", ""), str)
            and isinstance(row.get("ontology", ""), str) for row in result.values())
    else:
        valid = isinstance(result, list) and all(
            isinstance(row, (list, tuple)) and len(row) == 4 and all(isinstance(v, str) for v in row)
            for row in result)
    if not valid:
        raise ValueError(f"KAG {role} response has an invalid structure; see logged raw response")


def bind_formats(extractor, trace):
    """Scope the transport format around native invoke; preserve prompt and parser.

    Parsing failures propagate to the existing extractor retry decorators instead
    of becoming None and failing later during graph assembly.
    """
    prompts = {id(extractor.ner_prompt): "entities", id(extractor.kn_prompt): "knowledge_units",
               id(extractor.triple_prompt): "triples"}
    original = extractor.llm.invoke

    @wraps(original)
    def invoke(variables, prompt_op, **kwargs):
        role = prompts[id(prompt_op)]
        token = CURRENT_RESPONSE.set((role, SCHEMAS[role]))
        try:
            kwargs["with_except"] = True
            result = original(variables, prompt_op, **kwargs)
            validate_parsed(role, result)
            trace.emit("kag.response_validated", operation=role, parsed=result)
            return result
        except Exception as exc:
            trace.emit("kag.response_invalid", operation=role, error=str(exc))
            raise
        finally:
            CURRENT_RESPONSE.reset(token)

    extractor.llm.invoke = invoke
    trace.save("artifacts/kag_response_schemas.json", SCHEMAS)
