"""Keyed batches preserve per-item validation and shrink on output exhaustion."""
from pydantic import create_model
from .records import Record, batches
from .models import ModelResponseError, OutputLimitError


def ask_keyed(models, role, instruction, items, schema, entity_id, shared=None, validate=None, on_error=None):
    output = {}
    for page in batches(items, getattr(models, "batch_size", 4)):
        fields = {row["id"]: (schema, ...) for row in page}
        response_schema = create_model(role + "_batch", __base__=Record, **fields)
        def check(result):
            if validate:
                for item in page:
                    validate(item, getattr(result, item["id"]))
        try:
            result = models.ask(role, instruction + " Return one result under each supplied item ID.",
                dict(shared or {}, items=page), response_schema, entity_id, validator=check)
        except ModelResponseError as exc:
            if len(page) == 1:
                if on_error is None:
                    raise
                on_error(page[0], exc)
                continue
            if on_error is None and not isinstance(exc, OutputLimitError):
                raise
            midpoint = len(page) // 2
            for half in (page[:midpoint], page[midpoint:]):
                output.update(ask_keyed(models, role, instruction, half, schema, entity_id, shared, validate, on_error))
            continue
        output.update({key: getattr(result, key).model_dump() for key in fields})
    return output
