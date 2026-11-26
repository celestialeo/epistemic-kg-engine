"""Budget complete keyed requests and retain valid items during local repair."""
from pydantic import create_model, TypeAdapter
from .records import Record
from .models import ModelResponseError, OutputLimitError, request_budget
from .settings import estimated_tokens, setting


def ask_keyed(models, role, instruction, items, schema, entity_id, shared=None, validate=None, on_error=None,
              schema_for_item=None):
    output = {}
    options = getattr(models, 'options', {})
    maximum = options.get('num_predict', setting('model', 'max_output_tokens'))
    context = options.get('num_ctx', setting('model', 'context_tokens'))
    per_item = max(256, min(1536, estimated_tokens(TypeAdapter(schema).json_schema())))
    instruction += ' Return one result under each supplied item ID.'

    def request_spec(page):
        response_schema = create_model(role + '_batch', __base__=Record,
                                       **{row['id']: (schema_for_item(row) if schema_for_item else schema, ...) for row in page})
        reserve = maximum if len(page) == 1 else min(maximum, per_item * len(page))
        response_schema._pipeline_output_tokens = reserve
        request_options = dict(num_ctx=context, num_predict=reserve)
        payload = dict(shared or {}, items=page)
        fits = request_budget(instruction, payload, response_schema, request_options)['fits']
        return response_schema, payload, fits

    def execute(page, feedback=None):
        response_schema, payload, fits = request_spec(page)
        if not fits and len(page) > 1:
            midpoint = len(page) // 2
            execute(page[:midpoint]); execute(page[midpoint:])
            return
        def check_single(result):
            if validate:
                validate(page[0], getattr(result, page[0]['id']))
        try:
            result = models.ask(role, instruction + (('\nCorrect this specific validation failure: ' + feedback) if feedback else ''),
                payload, response_schema, entity_id,
                validator=check_single if len(page) == 1 and validate else None)
        except ModelResponseError as exc:
            if len(page) == 1:
                if on_error is None: raise
                on_error(page[0], exc)
                return
            if on_error is None and not isinstance(exc, OutputLimitError): raise
            midpoint = len(page) // 2
            execute(page[:midpoint]); execute(page[midpoint:])
            return
        for item in page:
            value = getattr(result, item['id'])
            if validate and len(page) > 1:
                try:
                    validate(item, value)
                except (ValueError, ModelResponseError) as exc:
                    execute([item], str(exc))
                    continue
            output[item['id']] = value.model_dump()

    page = []
    cap = getattr(models, 'batch_size', None)
    for item in items:
        proposed = page + [item]
        _, _, fits = request_spec(proposed)
        if page and (not fits or per_item * len(proposed) > maximum or (cap and len(proposed) > cap)):
            execute(page)
            page = []
        page.append(item)
    if page:
        execute(page)
    return output
